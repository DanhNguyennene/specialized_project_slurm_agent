from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests
import time
from collections import deque

__all__ = ["get_all_links_iterative"]


def get_all_links_iterative(start_url, max_depth=None, delay=1.0, max_pages=None):
    """
    Iteratively extract all links from a website (avoids recursion depth limits)

    Args:
        start_url: The starting URL to crawl
        max_depth: Maximum depth to crawl (None for unlimited)
        delay: Delay between requests in seconds
        max_pages: Maximum number of pages to visit (None for unlimited)
    """
    visited_urls = set()
    all_endpoints = set()
    base_domain = urlparse(start_url).netloc

    # Queue stores (url, depth) tuples
    queue = deque([(start_url, 0)])

    while queue and (max_pages is None or len(visited_urls) < max_pages):
        current_url, current_depth = queue.popleft()

        # Check depth limit
        if max_depth is not None and current_depth > max_depth:
            continue

        # Skip if already visited
        if current_url in visited_urls:
            continue

        print(f"Crawling (depth {current_depth}): {current_url}")
        visited_urls.add(current_url)

        try:
            # Add delay to be respectful
            time.sleep(delay)

            response = requests.get(current_url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a', href=True)

            new_links_count = 0
            for link in links:
                href = link['href']
                absolute_url = urljoin(current_url, href)

                # Filter to same domain only
                if urlparse(absolute_url).netloc == base_domain:
                    all_endpoints.add(absolute_url)

                    # Add to queue if not visited
                    if absolute_url not in visited_urls:
                        queue.append((absolute_url, current_depth + 1))
                        new_links_count += 1

            print(f"  Found {new_links_count} new links to crawl")

        except requests.RequestException as e:
            print(f"  Error fetching {current_url}: {e}")
        except Exception as e:
            print(f"  Unexpected error for {current_url}: {e}")

    return sorted(all_endpoints), visited_urls


# Usage example
if __name__ == "__main__":
    start_url = "https://docs.asterisk.org"  # Replace with your target URL

    print("Starting iterative crawl...")
    all_links, visited = get_all_links_iterative(
        start_url,
        max_depth=2,  # Limit depth
        delay=1.0,  # 1 second delay
        max_pages=50  # Stop after 50 pages
    )

    print(f"\n--- Crawling Complete ---")
    print(f"Total unique endpoints found: {len(all_links)}")
    print(f"Total pages visited: {len(visited)}")

    # Save results to file
    with open("crawled_endpoints.txt", "w") as f:
        for link in all_links:
            f.write(f"{link}\n")

    print("Results saved to crawled_endpoints.txt")