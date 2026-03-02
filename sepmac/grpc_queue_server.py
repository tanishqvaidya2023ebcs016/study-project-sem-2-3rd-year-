"""
gRPC Queue Server — manages Redis queue + deduplication.
Runs on localhost:50051
"""

import sys
import os
import time
import logging
from concurrent import futures

import grpc
import redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'generated'))
import crawler_pb2
import crawler_pb2_grpc

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [QueueServer] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class QueueServiceServicer(crawler_pb2_grpc.QueueServiceServicer):

    QUEUE_KEY = "crawler:url_queue"
    VISITED_KEY = "crawler:visited"
    PROCESSING_KEY = "crawler:processing"
    ENQUEUED_KEY = "crawler:enqueued"

    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
            socket_connect_timeout=5,
            retry_on_timeout=True
        )
        self.redis_client.ping()
        logger.info(f"Connected to Redis at {redis_host}:{redis_port}")

    def _normalize_url(self, url):
        url = url.strip().rstrip('/')
        if '#' in url:
            url = url.split('#')[0]
        return url

    def GetNextURL(self, request, context):
        response = crawler_pb2.GetNextURLResponse()

        lua_script = """
        local url = redis.call('LPOP', KEYS[1])
        if url then
            redis.call('SREM', KEYS[2], url)
            redis.call('SADD', KEYS[3], url)
            return url
        end
        return nil
        """

        try:
            result = self.redis_client.eval(
                lua_script, 3,
                self.QUEUE_KEY, self.ENQUEUED_KEY, self.PROCESSING_KEY
            )

            if result:
                response.url = result
                response.queue_empty = False
                logger.info(f"[{request.crawler_id}] LPOP: {result}")
            else:
                response.url = ""
                response.queue_empty = True

        except redis.RedisError as e:
            logger.error(f"Redis error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

        return response

    def AddURLs(self, request, context):
        added = 0

        lua_script = """
        local added = 0
        for i, url in ipairs(ARGV) do
            local is_visited = redis.call('SISMEMBER', KEYS[1], url)
            local is_enqueued = redis.call('SISMEMBER', KEYS[2], url)
            local is_processing = redis.call('SISMEMBER', KEYS[3], url)
            if is_visited == 0 and is_enqueued == 0 and is_processing == 0 then
                redis.call('RPUSH', KEYS[4], url)
                redis.call('SADD', KEYS[2], url)
                added = added + 1
            end
        end
        return added
        """

        try:
            urls = [self._normalize_url(u) for u in request.urls if u.strip()]
            urls = [u for u in urls if u]

            if urls:
                added = self.redis_client.eval(
                    lua_script, 4,
                    self.VISITED_KEY, self.ENQUEUED_KEY,
                    self.PROCESSING_KEY, self.QUEUE_KEY,
                    *urls
                )
                logger.info(f"[{request.crawler_id}] Added {added}/{len(urls)} URLs")

        except redis.RedisError as e:
            logger.error(f"Redis error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)

        return crawler_pb2.AddURLsResponse(added_count=added)

    def MarkVisited(self, request, context):
        url = self._normalize_url(request.url)
        try:
            pipe = self.redis_client.pipeline()
            pipe.sadd(self.VISITED_KEY, url)
            pipe.srem(self.PROCESSING_KEY, url)
            pipe.srem(self.ENQUEUED_KEY, url)
            pipe.lrem(self.QUEUE_KEY, 0, url)
            pipe.execute()
            return crawler_pb2.MarkVisitedResponse(success=True)
        except redis.RedisError as e:
            logger.error(f"Redis error: {e}")
            return crawler_pb2.MarkVisitedResponse(success=False)

    def IsVisited(self, request, context):
        url = self._normalize_url(request.url)
        try:
            visited = self.redis_client.sismember(self.VISITED_KEY, url)
            return crawler_pb2.IsVisitedResponse(visited=bool(visited))
        except redis.RedisError:
            return crawler_pb2.IsVisitedResponse(visited=False)

    def SeedURLs(self, request, context):
        seeded = 0
        try:
            pipe = self.redis_client.pipeline()
            for url in request.urls:
                normalized = self._normalize_url(url)
                if not normalized:
                    continue
                if (not self.redis_client.sismember(self.VISITED_KEY, normalized) and
                        not self.redis_client.sismember(self.ENQUEUED_KEY, normalized)):
                    pipe.rpush(self.QUEUE_KEY, normalized)
                    pipe.sadd(self.ENQUEUED_KEY, normalized)
                    seeded += 1
            pipe.execute()
            logger.info(f"Seeded {seeded} URLs")
        except redis.RedisError as e:
            logger.error(f"Redis error: {e}")

        return crawler_pb2.SeedURLsResponse(seeded_count=seeded)

    def GetStats(self, request, context):
        try:
            queue_size = self.redis_client.llen(self.QUEUE_KEY)
            visited_count = self.redis_client.scard(self.VISITED_KEY)
            return crawler_pb2.GetStatsResponse(
                queue_size=queue_size, visited_count=visited_count
            )
        except redis.RedisError:
            return crawler_pb2.GetStatsResponse(queue_size=0, visited_count=0)


def serve():
    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = int(os.environ.get('REDIS_PORT', 6379))
    grpc_port = os.environ.get('GRPC_PORT', '50051')

    for attempt in range(30):
        try:
            r = redis.Redis(host=redis_host, port=redis_port)
            r.ping()
            logger.info("Redis ready!")
            break
        except (redis.ConnectionError, redis.TimeoutError):
            logger.info(f"Waiting for Redis... ({attempt + 1})")
            time.sleep(2)
    else:
        logger.error("Cannot connect to Redis")
        sys.exit(1)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    servicer = QueueServiceServicer(redis_host, redis_port)
    crawler_pb2_grpc.add_QueueServiceServicer_to_server(servicer, server)

    server.add_insecure_port(f'0.0.0.0:{grpc_port}')
    server.start()
    logger.info(f"Queue Server started on port {grpc_port}")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=5)


if __name__ == '__main__':
    serve()