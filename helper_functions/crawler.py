import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, Set
from urllib.parse import urlparse

from haystack.schema import Document
from haystack.lazy_imports import LazyImport

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from selenium.webdriver.chrome.options import Options
from haystack.nodes import Crawler
from chromedriver_py import binary_path


class CustomCrawler(Crawler):
    def __init__(
        self,
        urls: Optional[List[str]] = None,
        crawler_depth: int = 1,
        filter_urls: Optional[List] = None,
        id_hash_keys: Optional[List[str]] = None,
        extract_hidden_text=True,
        loading_wait_time: Optional[int] = None,
        output_dir: Union[str, Path, None] = None,
        overwrite_existing_files=True,
        file_path_meta_field_name: Optional[str] = None,
        crawler_naming_function: Optional[Callable[[str, str], str]] = None,
        webdriver_options: Optional[List[str]] = None,
    ):
        """
        Init object with basic params for crawling (can be overwritten later).

        :param urls: List of http(s) address(es) (can also be supplied later when calling crawl())
        :param crawler_depth: How many sublinks to follow from the initial list of URLs. Can be any integer >= 0.
                                For example:
                                0: Only initial list of urls.
                                1: Follow links found on the initial URLs (but no further).
                                2: Additionally follow links found on the second-level URLs.
        :param filter_urls: Optional list of regular expressions that the crawled URLs must comply with.
            All URLs not matching at least one of the regular expressions will be dropped.
        :param id_hash_keys: Generate the document id from a custom list of strings that refer to the document's
            attributes. If you want to ensure you don't have duplicate documents in your DocumentStore but texts are
            not unique, you can modify the metadata and pass e.g. `"meta"` to this field (e.g. [`"content"`, `"meta"`]).
            In this case the id will be generated by using the content and the defined metadata.
        :param extract_hidden_text: Whether to extract the hidden text contained in page.
            E.g. the text can be inside a span with style="display: none"
        :param loading_wait_time: Seconds to wait for page loading before scraping. Recommended when page relies on
            dynamic DOM manipulations. Use carefully and only when needed. Crawler will have scraping speed impacted.
            E.g. 2: Crawler will wait 2 seconds before scraping page
        :param output_dir: If provided, the crawled documents will be saved as JSON files in this directory.
        :param overwrite_existing_files: Whether to overwrite existing files in output_dir with new content
        :param file_path_meta_field_name: If provided, the file path will be stored in this meta field.
        :param crawler_naming_function: A function mapping the crawled page to a file name.
            By default, the file name is generated from the processed page url (string compatible with Mac, Unix and Windows paths) and the last 6 digits of the MD5 sum of this unprocessed page url.
            E.g. 1) crawler_naming_function=lambda url, page_content: re.sub("[<>:'/\\|?*\0 ]", "_", link)
                    This example will generate a file name from the url by replacing all characters that are not allowed in file names with underscores.
                 2) crawler_naming_function=lambda url, page_content: hashlib.md5(f"{url}{page_content}".encode("utf-8")).hexdigest()
                    This example will generate a file name from the url and the page content by using the MD5 hash of the concatenation of the url and the page content.
        :param webdriver_options: A list of options to send to Selenium webdriver. If none is provided,
            Crawler uses, as a default option, a reasonable selection for operating locally, on restricted docker containers,
            and avoids using GPU.
            Crawler always appends the following option: "--headless"
            For example: 1) ["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--single-process"]
                    These are the default options which disable GPU, disable shared memory usage
                    and spawn a single process.
                 2) ["--no-sandbox"]
                    This option disables the sandbox, which is required for running Chrome as root.
                 3) ["--remote-debugging-port=9222"]
                    This option enables remote debug over HTTP.
            See [Chromium Command Line Switches](https://peter.sh/experiments/chromium-command-line-switches/) for more details on the available options.
            If your crawler fails, raising a `selenium.WebDriverException`, this [Stack Overflow thread](https://stackoverflow.com/questions/50642308/webdriverexception-unknown-error-devtoolsactiveport-file-doesnt-exist-while-t) can be helpful. Contains useful suggestions for webdriver_options.
        """
        # selenium_import.check()
        # super().__init__()

        IN_COLAB = "google.colab" in sys.modules
        IN_AZUREML = os.environ.get("AZUREML_ENVIRONMENT_IMAGE", None) == "True"
        IN_WINDOWS = sys.platform in ["win32", "cygwin"]
        IS_ROOT = not IN_WINDOWS and os.geteuid() == 0  # type: ignore   # This is a mypy issue of sorts, that fails on Windows.

        if webdriver_options is None:
            webdriver_options = ["--headless", "--disable-gpu", "--disable-dev-shm-usage", "--single-process"]
        webdriver_options.append("--headless")
        if IS_ROOT or IN_WINDOWS or IN_COLAB:
            webdriver_options.append("--no-sandbox")
        if IS_ROOT or IN_WINDOWS:
            webdriver_options.append("--remote-debugging-port=9222")
        if IN_COLAB or IN_AZUREML:
            webdriver_options.append("--disable-dev-shm-usage")

        options = Options()
        for option in set(webdriver_options):
            options.add_argument(option)

        self.driver = webdriver.Chrome(service=Service(binary_path), options=options)
        self.urls = urls
        self.crawler_depth = crawler_depth
        self.filter_urls = filter_urls
        self.overwrite_existing_files = overwrite_existing_files
        self.id_hash_keys = id_hash_keys
        self.extract_hidden_text = extract_hidden_text
        self.loading_wait_time = loading_wait_time
        self.crawler_naming_function = crawler_naming_function
        self.output_dir = output_dir
        self.file_path_meta_field_name = file_path_meta_field_name