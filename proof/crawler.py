"""
Crawler - High Quality System Design Link Crawler
Only crawls and stores genuinely useful system design resources.
Filters out login pages, noise, ads, and low-quality content.
"""

import sys
import os
import time
import logging
import re
from urllib.parse import urljoin, urlparse, parse_qs

import grpc
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'generated'))
import crawler_pb2
import crawler_pb2_grpc

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [Crawler-Mac] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# QUALITY CONFIGURATION
# ============================================================

# Tier 1: Best system design resources — crawl deeply
TIER1_DOMAINS = {
    'bytebytego.com',
    'hellointerview.com',
    'highscalability.com',
    'martinfowler.com',
    'donnemartin.com',
    'systemdesign.one',
    'blog.bytebytego.com',
    'newsletter.systemdesign.one',
    'engineeringatscale.substack.com',
    'newsletter.pragmaticengineer.com',
    'blog.pragmaticengineer.com',
    'architecturenotes.co',
    'systemdesignschool.io',
    'designgurus.io',
    'interviewready.io',
}

# Tier 2: Good resources — crawl but only system design sections
TIER2_DOMAINS = {
    'github.com',
    'medium.com',
    'dev.to',
    'engineering.fb.com',
    'engineering.atspotify.com',
    'netflixtechblog.com',
    'eng.uber.com',
    'blog.twitter.com',
    'engineering.linkedin.com',
    'aws.amazon.com',
    'cloud.google.com',
    'learn.microsoft.com',
    'docs.microsoft.com',
    'research.google',
    'static.googleusercontent.com',
    'instagram-engineering.com',
    'discord.com/blog',
    'slack.engineering',
    'engineering.shopify.com',
    'dropbox.tech',
    'airbnb.io',
    'stripe.com/blog',
}

# Tier 3: Educational — only specific paths
TIER3_DOMAINS = {
    'educative.io',
    'geeksforgeeks.org',
    'leetcode.com',
    'stackoverflow.com',
    'wikipedia.org',
    'baeldung.com',
    'freecodecamp.org',
    'tutorialspoint.com',
}

# Combine all allowed domains
ALLOWED_DOMAINS = TIER1_DOMAINS | TIER2_DOMAINS | TIER3_DOMAINS

# ============================================================
# GITHUB SPECIFIC: Only these repos/paths are valuable
# ============================================================

GITHUB_QUALITY_REPOS = [
    'donnemartin/system-design-primer',
    'karanpratapsingh/system-design',
    'ByteByteGoHq/system-design-101',
    'systemdesign42/system-design',
    'checkcheckzz/system-design-interview',
    'madd86/awesome-system-design',
    'shashank88/system_design',
    'binhnguyennus/awesome-scalability',
    'kilimchoi/engineering-blogs',
    'resumejob/system-design-algorithms',
    'InterviewReady/system-design-resources',
    'ashishps1/awesome-system-design-resources',
    'codersguild/System-Design',
    'prasadgujar/low-level-design-primer',
    'yangshun/tech-interview-handbook',
    'alex/what-happens-when',
    'jguamie/system-design',
    'lei-hsia/grokking-system-design',
]

GITHUB_QUALITY_PATHS = [
    '/blob/master/',   # README content
    '/blob/main/',     # README content
    '/tree/master/',   # Directory listing
    '/tree/main/',     # Directory listing
]

# ============================================================
# JUNK FILTERS: URLs to always reject
# ============================================================

# URL path patterns that are NEVER useful
BLOCKED_PATH_PATTERNS = [
    # Auth / Account
    r'/login', r'/signin', r'/signup', r'/register',
    r'/auth/', r'/oauth', r'/sso/',
    r'/password', r'/forgot', r'/reset-password',
    r'/account', r'/settings', r'/profile',
    r'/preferences', r'/notifications',

    # GitHub noise
    r'/pulls$', r'/issues$', r'/issues\?',
    r'/commit/', r'/commits/', r'/compare/',
    r'/blame/', r'/raw/', r'/edit/',
    r'/delete/', r'/fork', r'/forks$',
    r'/stargazers', r'/watchers', r'/network',
    r'/graphs/', r'/pulse', r'/projects',
    r'/actions', r'/security', r'/packages',
    r'/releases/tag/', r'/archive/',
    r'/workflows/', r'\.git$',
    r'/sponsors', r'/marketplace',
    r'/codespaces', r'/copilot',

    # Social / Sharing
    r'/share\?', r'intent/tweet',
    r'facebook\.com/sharer', r'linkedin\.com/share',
    r'reddit\.com/submit',

    # E-commerce / Pricing
    r'/pricing', r'/plans', r'/subscribe',
    r'/cart', r'/checkout', r'/buy',
    r'/enterprise', r'/pro$',

    # Legal
    r'/terms', r'/privacy', r'/cookie',
    r'/legal', r'/dmca', r'/gdpr',

    # Support / Meta
    r'/contact', r'/support', r'/help$',
    r'/about$', r'/careers', r'/jobs',
    r'/press', r'/blog/tag/', r'/blog/page/',
    r'/category/', r'/tags/',

    # Media files
    r'\.(png|jpg|jpeg|gif|svg|ico|webp|mp4|mp3|pdf|zip|tar|gz)$',

    # API / feeds
    r'/api/', r'/rss', r'/feed', r'/sitemap',
    r'\.json$', r'\.xml$',

    # Tracking / Ads
    r'utm_', r'ref=', r'source=',
    r'/ads/', r'/sponsor',
    r'doubleclick', r'analytics',
    r'google-analytics', r'facebook.*pixel',
]

# Compile patterns for performance
BLOCKED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATH_PATTERNS]

# ============================================================
# QUALITY KEYWORDS: URL must contain at least one
# ============================================================

SYSTEM_DESIGN_KEYWORDS = [
    # Core system design
    'system-design', 'system_design', 'systemdesign',
    'system design',

    # Architecture
    'distributed-system', 'distributed_system',
    'microservices', 'monolith', 'architecture',
    'software-architecture', 'design-pattern',

    # Scalability
    'scalability', 'scale', 'high-availability',
    'fault-tolerance', 'fault-tolerant',
    'load-balancer', 'load-balancing',
    'horizontal-scaling', 'vertical-scaling',

    # Data
    'database-design', 'database-sharding', 'sharding',
    'replication', 'partitioning', 'indexing',
    'sql-vs-nosql', 'cap-theorem', 'acid',
    'eventual-consistency', 'strong-consistency',
    'data-modeling',

    # Caching
    'caching', 'cache-invalidation',
    'redis', 'memcached', 'cdn',

    # Messaging
    'message-queue', 'message-broker',
    'kafka', 'rabbitmq', 'pub-sub',
    'event-driven', 'event-sourcing',

    # Networking
    'api-design', 'api-gateway',
    'rest-api', 'graphql', 'grpc',
    'websocket', 'rate-limiting',
    'dns', 'reverse-proxy',

    # Specific designs
    'url-shortener', 'tiny-url',
    'chat-system', 'notification',
    'news-feed', 'newsfeed',
    'search-engine', 'web-crawler',
    'video-streaming', 'file-storage',
    'payment-system', 'ride-sharing',
    'hotel-booking', 'e-commerce',
    'social-network', 'twitter-design',
    'instagram-design', 'whatsapp-design',
    'youtube-design', 'netflix-design',
    'uber-design', 'dropbox-design',

    # Algorithms for SD
    'consistent-hashing', 'bloom-filter',
    'rate-limiter', 'circuit-breaker',
    'leader-election', 'consensus',
    'raft', 'paxos', 'gossip-protocol',
    'heartbeat', 'quorum',

    # Infrastructure
    'kubernetes', 'docker', 'containerization',
    'ci-cd', 'deployment', 'blue-green',
    'canary', 'service-mesh', 'observability',
    'monitoring', 'logging', 'tracing',

    # Interview specific
    'system-design-interview', 'design-interview',
    'grokking', 'interview-preparation',

    # Known quality authors/brands
    'bytebytego', 'donnemartin', 'system-design-primer',
    'hellointerview', 'designgurus',
    'pragmatic-engineer', 'highscalability',
    'martin-fowler',
]

# Content keywords — check page text for relevance
CONTENT_QUALITY_KEYWORDS = [
    'system design', 'distributed system', 'scalability',
    'load balancer', 'microservice', 'database design',
    'caching strategy', 'message queue', 'api gateway',
    'high availability', 'fault tolerance', 'cap theorem',
    'consistent hashing', 'data partitioning', 'sharding',
    'replication', 'horizontal scaling', 'vertical scaling',
    'latency', 'throughput', 'availability',
    'back-of-the-envelope', 'design requirements',
    'functional requirements', 'non-functional requirements',
    'trade-off', 'bottleneck',
]


class QualityFilter:
    """Filters URLs to ensure only high-quality system design links pass."""

    @staticmethod
    def is_blocked_url(url: str) -> bool:
        """Check if URL matches any blocked pattern."""
        for pattern in BLOCKED_PATTERNS_COMPILED:
            if pattern.search(url):
                return True
        return False

    @staticmethod
    def is_quality_github_url(url: str) -> bool:
        """
        GitHub URLs must be from known quality repos.
        Blocks: random repos, issues, PRs, user profiles, etc.
        """
        parsed = urlparse(url)
        if 'github.com' not in parsed.netloc:
            return True  # Not GitHub, skip this check

        path = parsed.path.strip('/')

        # Block GitHub homepage, explore, trending, etc.
        if path in ('', 'explore', 'trending', 'topics', 'collections'):
            return False

        # Block user profile pages (single segment paths)
        path_parts = path.split('/')
        if len(path_parts) == 1:
            return False  # Just /username

        # Check if it's a known quality repo
        if len(path_parts) >= 2:
            repo_path = f"{path_parts[0]}/{path_parts[1]}"
            if repo_path.lower() in [r.lower() for r in GITHUB_QUALITY_REPOS]:
                # Allow repo root, README, and content pages
                if len(path_parts) == 2:
                    return True  # Repo root
                # Allow blob/tree for content
                if len(path_parts) >= 3 and path_parts[2] in ('blob', 'tree', 'wiki'):
                    return True
                return False  # Other repo pages (issues, PRs, etc.)

        # For non-listed repos, check if the URL itself has SD keywords
        url_lower = url.lower()
        has_keyword = any(kw in url_lower for kw in [
            'system-design', 'system_design', 'distributed',
            'scalability', 'architecture', 'microservices',
            'design-pattern', 'awesome-system',
        ])

        if has_keyword and len(path_parts) == 2:
            return True  # Repo root with relevant name

        return False

    @staticmethod
    def is_quality_medium_url(url: str) -> bool:
        """Medium URLs must have system design content indicators."""
        parsed = urlparse(url)
        if 'medium.com' not in parsed.netloc:
            return True

        url_lower = url.lower()

        # Block medium homepage, tags listing, about pages
        if parsed.path in ('/', '', '/about', '/creators', '/membership'):
            return False

        # Must contain a system design keyword
        return any(kw in url_lower for kw in SYSTEM_DESIGN_KEYWORDS)

    @staticmethod
    def is_quality_educational_url(url: str) -> bool:
        """Educational sites — only system design paths."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        url_lower = url.lower()

        # GeeksForGeeks: only SD articles
        if 'geeksforgeeks.org' in domain:
            return any(kw in url_lower for kw in [
                'system-design', 'design-', 'scalab',
                'load-balanc', 'database', 'caching',
            ])

        # LeetCode: only discuss/system-design
        if 'leetcode.com' in domain:
            return 'system-design' in url_lower or 'discuss' in url_lower

        # StackOverflow: only system design tagged questions
        if 'stackoverflow.com' in domain:
            return any(kw in url_lower for kw in [
                'system-design', 'distributed', 'scalability',
                'architecture', 'microservices',
            ])

        # Wikipedia: only relevant articles
        if 'wikipedia.org' in domain:
            return any(kw in url_lower for kw in [
                'distributed', 'scalability', 'load_balancing',
                'consistent_hashing', 'cap_theorem', 'database_sharding',
                'microservices', 'message_queue', 'caching',
                'replication', 'consensus',
            ])

        return True

    @staticmethod
    def has_system_design_keyword(url: str) -> bool:
        """Check if URL contains at least one system design keyword."""
        url_lower = url.lower()
        return any(kw in url_lower for kw in SYSTEM_DESIGN_KEYWORDS)

    @staticmethod
    def is_tier1_domain(url: str) -> bool:
        """Check if URL is from a Tier 1 (always-quality) domain."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().lstrip('www.')
            return any(t1 in domain for t1 in TIER1_DOMAINS)
        except Exception:
            return False

    @staticmethod
    def get_domain(url: str) -> str:
        """Extract clean domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower().lstrip('www.')
        except Exception:
            return ""

    @staticmethod
    def is_allowed_domain(url: str) -> bool:
        """Check if URL domain is in any tier."""
        domain = QualityFilter.get_domain(url)
        return any(allowed in domain for allowed in ALLOWED_DOMAINS)

    @classmethod
    def is_quality_url(cls, url: str) -> tuple:
        """
        Main quality check. Returns (is_quality: bool, reason: str).

        Logic:
        1. Must be valid HTTP(S) URL
        2. Must NOT match blocked patterns (login, settings, etc.)
        3. Must be from an allowed domain
        4. Tier 1 domains: always accept (unless blocked)
        5. GitHub: must be from known quality repos
        6. Medium: must have SD keywords
        7. Educational sites: must be SD-specific
        8. All others: must have at least one SD keyword in URL
        """
        # Basic validation
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return False, "not http/https"
            if not parsed.netloc:
                return False, "no domain"
        except Exception:
            return False, "invalid url"

        # Check blocked patterns
        if cls.is_blocked_url(url):
            return False, "blocked pattern"

        # Check allowed domain
        if not cls.is_allowed_domain(url):
            return False, "domain not allowed"

        domain = cls.get_domain(url)

        # Tier 1: Always quality (bytebytego, hellointerview, etc.)
        if cls.is_tier1_domain(url):
            return True, "tier1 domain"

        # GitHub: strict quality check
        if 'github.com' in domain:
            if cls.is_quality_github_url(url):
                return True, "quality github repo"
            return False, "low-quality github url"

        # Medium: must have SD content
        if 'medium.com' in domain:
            if cls.is_quality_medium_url(url):
                return True, "quality medium article"
            return False, "non-SD medium url"

        # Educational sites: specific checks
        if any(ed in domain for ed in TIER3_DOMAINS):
            if cls.is_quality_educational_url(url):
                return True, "quality educational content"
            return False, "non-SD educational url"

        # Tier 2 (tech blogs): must have keyword
        if any(t2 in domain for t2 in TIER2_DOMAINS):
            if cls.has_system_design_keyword(url):
                return True, "tier2 with SD keyword"
            # Tech blogs are often quality even without keyword in URL
            return True, "tier2 tech blog"

        # Fallback: must have keyword
        if cls.has_system_design_keyword(url):
            return True, "has SD keyword"

        return False, "no SD relevance"


class ContentAnalyzer:
    """Analyzes page content to verify system design relevance."""

    @staticmethod
    def is_quality_content(html: str, min_keyword_count: int = 2) -> tuple:
        """
        Check if page content is actually about system design.
        Returns (is_quality: bool, keyword_count: int, found_keywords: list)
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove script, style, nav, footer, header
            for tag in soup.find_all(['script', 'style', 'nav', 'footer',
                                       'header', 'aside']):
                tag.decompose()

            text = soup.get_text(separator=' ').lower()

            # Count quality keywords in content
            found_keywords = []
            for keyword in CONTENT_QUALITY_KEYWORDS:
                if keyword in text:
                    found_keywords.append(keyword)

            keyword_count = len(found_keywords)
            is_quality = keyword_count >= min_keyword_count

            return is_quality, keyword_count, found_keywords

        except Exception:
            return False, 0, []


class DistributedCrawler:
    def __init__(self, crawler_id: str, queue_server: str, file_server: str):
        self.crawler_id = crawler_id
        self.queue_server = queue_server
        self.file_server = file_server
        self.quality_filter = QualityFilter()
        self.content_analyzer = ContentAnalyzer()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        })

        # Stats
        self.stats = {
            'crawled': 0,
            'stored': 0,
            'filtered_out': 0,
            'errors': 0,
            'content_rejected': 0,
        }

        # gRPC channels
        self.queue_channel = None
        self.queue_stub = None
        self.file_channel = None
        self.file_stub = None

        self._connect()

    def _connect(self):
        """Establish gRPC connections."""
        logger.info(f"Connecting to Queue Server at {self.queue_server}")
        self.queue_channel = grpc.insecure_channel(
            self.queue_server,
            options=[
                ('grpc.keepalive_time_ms', 10000),
                ('grpc.keepalive_timeout_ms', 5000),
                ('grpc.keepalive_permit_without_calls', True),
                ('grpc.enable_retries', 1),
            ]
        )
        self.queue_stub = crawler_pb2_grpc.QueueServiceStub(self.queue_channel)

        logger.info(f"Connecting to File Server at {self.file_server}")
        self.file_channel = grpc.insecure_channel(
            self.file_server,
            options=[
                ('grpc.keepalive_time_ms', 10000),
                ('grpc.keepalive_timeout_ms', 5000),
                ('grpc.keepalive_permit_without_calls', True),
                ('grpc.enable_retries', 1),
            ]
        )
        self.file_stub = crawler_pb2_grpc.FileServiceStub(self.file_channel)

    def _extract_links(self, url: str, html: str) -> list:
        """
        Extract and filter links from HTML.
        Only returns high-quality system design links.
        """
        quality_links = []
        rejected_count = 0

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove nav, footer, sidebar — links there are usually junk
            for tag in soup.find_all(['nav', 'footer', 'aside',
                                       'header']):
                tag.decompose()

            for tag in soup.find_all('a', href=True):
                href = tag['href']

                # Skip anchors, javascript, mailto
                if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                    continue

                # Resolve relative URLs
                absolute_url = urljoin(url, href)

                # Clean URL — remove tracking params
                absolute_url = self._clean_url(absolute_url)

                # Quality check
                is_quality, reason = self.quality_filter.is_quality_url(absolute_url)

                if is_quality:
                    quality_links.append(absolute_url)
                else:
                    rejected_count += 1

        except Exception as e:
            logger.error(f"Error extracting links from {url}: {e}")

        unique_links = list(set(quality_links))

        logger.info(
            f"Extracted {len(unique_links)} quality links "
            f"(rejected {rejected_count} junk links)"
        )

        return unique_links

    def _clean_url(self, url: str) -> str:
        """Remove tracking parameters and clean URL."""
        try:
            parsed = urlparse(url)

            # Remove tracking query params
            if parsed.query:
                params = parse_qs(parsed.query)
                clean_params = {
                    k: v for k, v in params.items()
                    if not any(track in k.lower() for track in [
                        'utm_', 'ref', 'source', 'campaign',
                        'fbclid', 'gclid', 'mc_', 'ocid',
                    ])
                }

                if clean_params:
                    query_string = '&'.join(
                        f"{k}={v[0]}" for k, v in clean_params.items()
                    )
                    url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query_string}"
                else:
                    url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

            # Remove fragments
            if '#' in url:
                url = url.split('#')[0]

            # Remove trailing slash
            url = url.rstrip('/')

            return url

        except Exception:
            return url

    def _get_next_url(self) -> tuple:
        """Get next URL from queue via gRPC."""
        try:
            response = self.queue_stub.GetNextURL(
                crawler_pb2.GetNextURLRequest(crawler_id=self.crawler_id),
                timeout=10
            )
            return response.url, response.queue_empty
        except grpc.RpcError as e:
            logger.error(f"gRPC error getting next URL: {e.code()}: {e.details()}")
            return "", True

    def _add_urls_to_queue(self, urls: list):
        """Add discovered URLs to queue via gRPC."""
        if not urls:
            return
        try:
            response = self.queue_stub.AddURLs(
                crawler_pb2.AddURLsRequest(
                    urls=urls,
                    crawler_id=self.crawler_id
                ),
                timeout=10
            )
            logger.info(f"Added {response.added_count} new quality URLs to queue")
        except grpc.RpcError as e:
            logger.error(f"gRPC error adding URLs: {e.code()}: {e.details()}")

    def _mark_visited(self, url: str):
        """Mark URL as visited via gRPC."""
        try:
            self.queue_stub.MarkVisited(
                crawler_pb2.MarkVisitedRequest(
                    url=url,
                    crawler_id=self.crawler_id
                ),
                timeout=10
            )
        except grpc.RpcError as e:
            logger.error(f"gRPC error marking visited: {e.code()}: {e.details()}")

    def _store_link(self, url: str):
        """Store crawled link to file on Windows via gRPC."""
        try:
            response = self.file_stub.StoreLink(
                crawler_pb2.StoreLinkRequest(
                    url=url,
                    crawler_id=self.crawler_id,
                    timestamp=int(time.time())
                ),
                timeout=10
            )
            if response.success:
                self.stats['stored'] += 1
                logger.info(f"✅ Stored quality link: {url}")
        except grpc.RpcError as e:
            logger.error(f"gRPC error storing link: {e.code()}: {e.details()}")

    def crawl_url(self, url: str):
        """Crawl a single URL with quality checks."""
        logger.info(f"🔍 Crawling: {url}")

        # Pre-crawl quality check
        is_quality, reason = self.quality_filter.is_quality_url(url)
        if not is_quality:
            logger.info(f"⛔ Skipping (pre-crawl filter: {reason}): {url}")
            self._mark_visited(url)
            self.stats['filtered_out'] += 1
            return

        try:
            response = self.session.get(
                url, timeout=15, allow_redirects=True,
                headers={'Accept': 'text/html,application/xhtml+xml'}
            )
            response.raise_for_status()

            # Check content type — only HTML
            content_type = response.headers.get('content-type', '')
            if 'text/html' not in content_type and 'xhtml' not in content_type:
                logger.info(f"⛔ Skipping non-HTML content: {content_type}")
                self._mark_visited(url)
                self.stats['filtered_out'] += 1
                return

            html = response.text

            # Post-crawl content quality check
            # Tier 1 domains skip content check — they are always quality
            if not self.quality_filter.is_tier1_domain(url):
                is_quality_content, kw_count, found_kws = \
                    self.content_analyzer.is_quality_content(html, min_keyword_count=2)

                if not is_quality_content:
                    logger.info(
                        f"⛔ Content not relevant enough "
                        f"(only {kw_count} SD keywords found): {url}"
                    )
                    self._mark_visited(url)
                    self.stats['content_rejected'] += 1
                    return

                logger.info(
                    f"✅ Content verified ({kw_count} keywords: "
                    f"{', '.join(found_kws[:5])})"
                )

            # Extract quality links
            discovered_links = self._extract_links(url, html)

            # Store the crawled link on Windows
            self._store_link(url)

            # Mark as visited
            self._mark_visited(url)
            self.stats['crawled'] += 1

            # Add discovered links to queue
            if discovered_links:
                self._add_urls_to_queue(discovered_links)

            # Be polite — don't hammer servers
            time.sleep(1.5)

        except requests.RequestException as e:
            logger.error(f"❌ HTTP error crawling {url}: {e}")
            self._mark_visited(url)
            self.stats['errors'] += 1
        except Exception as e:
            logger.error(f"❌ Unexpected error crawling {url}: {e}")
            self._mark_visited(url)
            self.stats['errors'] += 1

    def _print_stats(self, crawled_count):
        """Print detailed crawler stats."""
        logger.info("=" * 60)
        logger.info(f"📊 CRAWLER STATS — {self.crawler_id}")
        logger.info(f"  Crawled:          {self.stats['crawled']}")
        logger.info(f"  Stored:           {self.stats['stored']}")
        logger.info(f"  Filtered (URL):   {self.stats['filtered_out']}")
        logger.info(f"  Filtered (Content): {self.stats['content_rejected']}")
        logger.info(f"  Errors:           {self.stats['errors']}")
        quality_rate = (
            self.stats['stored'] / max(crawled_count, 1) * 100
        )
        logger.info(f"  Quality Rate:     {quality_rate:.1f}%")

        try:
            stats = self.queue_stub.GetStats(
                crawler_pb2.GetStatsRequest(), timeout=5
            )
            logger.info(f"  Queue Size:       {stats.queue_size}")
            logger.info(f"  Total Visited:    {stats.visited_count}")
        except grpc.RpcError:
            pass

        logger.info("=" * 60)

    def run(self, max_urls: int = 100):
        """Main crawler loop."""
        crawled_count = 0
        empty_count = 0
        max_empty_retries = 10

        logger.info(f"🚀 Starting crawler {self.crawler_id}, max_urls={max_urls}")
        logger.info(f"   Quality mode: ON")
        logger.info(f"   Tier 1 domains: {len(TIER1_DOMAINS)}")
        logger.info(f"   Blocked patterns: {len(BLOCKED_PATH_PATTERNS)}")

        while crawled_count < max_urls:
            url, queue_empty = self._get_next_url()

            if queue_empty or not url:
                empty_count += 1
                if empty_count >= max_empty_retries:
                    logger.info("Queue empty for too long. Stopping.")
                    break
                logger.info(
                    f"Queue empty, waiting... ({empty_count}/{max_empty_retries})"
                )
                time.sleep(5)
                continue

            empty_count = 0
            self.crawl_url(url)
            crawled_count += 1

            # Print stats every 10 crawls
            if crawled_count % 10 == 0:
                self._print_stats(crawled_count)

        logger.info("🏁 CRAWLER FINISHED")
        self._print_stats(crawled_count)

    def close(self):
        """Clean up connections."""
        if self.queue_channel:
            self.queue_channel.close()
        if self.file_channel:
            self.file_channel.close()
        self.session.close()


def seed_initial_urls(queue_stub):
    """Seed with ONLY high-quality system design starting points."""
    seed_urls = [
        # Tier 1: Best resources
        "https://bytebytego.com/courses/system-design-interview/scale-from-zero-to-millions-of-users",
        "https://www.hellointerview.com/learn/system-design/in-a-hurry/introduction",
        "https://highscalability.com/",
        "https://martinfowler.com/articles/patterns-of-distributed-systems/",
        "https://architecturenotes.co/",

        # Top GitHub repos
        "https://github.com/donnemartin/system-design-primer",
        "https://github.com/karanpratapsingh/system-design",
        "https://github.com/ByteByteGoHq/system-design-101",
        "https://github.com/ashishps1/awesome-system-design-resources",
        "https://github.com/binhnguyennus/awesome-scalability",

        # Tech company blogs — system design posts
        "https://netflixtechblog.com/",
        "https://eng.uber.com/",
        "https://engineering.fb.com/",
        "https://instagram-engineering.com/",
        "https://slack.engineering/",
        "https://dropbox.tech/",
        "https://airbnb.io/",

        # Educational
        "https://www.educative.io/courses/grokking-modern-system-design-interview-for-engineers-managers",
        "https://www.designgurus.io/course/grokking-the-system-design-interview",
    ]

    try:
        response = queue_stub.SeedURLs(
            crawler_pb2.SeedURLsRequest(urls=seed_urls),
            timeout=10
        )
        logger.info(f"🌱 Seeded {response.seeded_count} high-quality URLs")
    except grpc.RpcError as e:
        logger.error(f"Error seeding URLs: {e}")


def main():
    queue_server = os.environ.get('QUEUE_SERVER', 'localhost:50051')
    file_server = os.environ.get('FILE_SERVER', '100.x.x.2:50052')
    crawler_id = os.environ.get('CRAWLER_ID', 'crawler-mac')
    max_urls = int(os.environ.get('MAX_URLS', '100'))
    should_seed = os.environ.get('SEED_URLS', 'true').lower() == 'true'

    crawler = DistributedCrawler(crawler_id, queue_server, file_server)

    try:
        if should_seed:
            seed_initial_urls(crawler.queue_stub)
            time.sleep(2)

        crawler.run(max_urls=max_urls)
    finally:
        crawler.close()


if __name__ == '__main__':
    main()