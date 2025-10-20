import aiohttp
import asyncio
from bs4 import BeautifulSoup
import html2text
import re

__all__ = ["crawl"]

async def crawl(url: str) -> str:
    # fetch content
    async def fetch_html(url_to_craw):
        async with aiohttp.ClientSession() as crawler:
            async with crawler.get(url_to_craw) as response:
                # Ensure the response is successful
                response.raise_for_status()
                # Read the HTML content as text
                text = await response.text()

                return text

    def html_to_markdown(html):
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        # Initialize html2text with custom settings
        h = html2text.HTML2Text()
        h.ignore_links = False  # Keep links in Markdown
        # h.body_width = 0  # Disable line wrapping
        h.ul_item_mark = '-'  # Use - for lists
        h.emphasis_mark = '*'  # Use * for emphasis
        # Extract the article content
        article = soup.find('article', class_='md-content__inner md-typeset')
        if not article:
            return ""
        # Convert the article content to Markdown
        markdown_content = h.handle(str(article))
        # Clean up extra newlines and unwanted characters
        markdown_content = markdown_content.strip()
        markdown_content = markdown_content.replace('\n\n\n', '\n\n')  # Reduce excessive newlines

        return markdown_content

    def convert_code_block(text):
        """
        Extract code blocks from the specified pattern format.

        Pattern to match:
        {string}

        {lines of number}

        {|}

        {lines of code}

        {---|---}

        Returns only the {lines of code} part.
        """
        # Pattern to match the entire structure and capture the code part
        pattern = r'\n\s*\s*\n(\s*\d+(?:\s+\d+)*\s*)\n\|\n\n\s*\n\s*\n(.*?)\s*\n\s*\n\s*\|?---\|---'
        matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)

        if matches:
            # Return only the code part (second group), cleaned up
            for match in matches:
                # remove number lines block and add <code> header
                num_lines = match[0]
                num_lines = f"\n    \n    \n{num_lines}\n" + r"\|" + f"\n\n    \n    \n"
                text = re.sub(num_lines, "\n---\n", text, flags=re.MULTILINE | re.DOTALL)

                # and </code> finish
                code_tail = "      \n  \n" + r"---\|---(\s*?)"
                text = re.sub(code_tail, "---\n", text)
        return text

    # Run the async function and get the HTML
    content = await fetch_html(url)
    # extract content from full html and convert to markdown
    markdown_result = html_to_markdown(content)

    return convert_code_block(markdown_result)

if __name__ == "__main__":
    markdown = asyncio.run(crawl("https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Asterisk_REST_Interface/Endpoints_REST_API/"))
    with open("test_suite_doc.md", "w") as f:
        f.write(markdown)