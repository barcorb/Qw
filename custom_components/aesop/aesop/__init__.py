"""Aesop interface."""

import datetime
import time
import json
import logging
import os.path
import pickle
import re
from bs4 import BeautifulSoup
from dateutil.parser import parse
import requests
from requests.auth import AuthBase
import requests_cache
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.firefox.options import Options

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)
logging.debug("test")
HTML_PARSER = 'html.parser'
ATTRIBUTION = 'Information provided by Aesop'
LOGIN_URL = 'https://sub.aesoponline.com/Substitute/Home'
LOGIN_TIMEOUT = 10
COOKIE_PATH = './aesop_cookies.pickle'
CACHE_PATH = './aesop_cache'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36 Edge/12.246'
CHROME_WEBDRIVER_ARGS = [
    '--headless', '--user-agent={}'.format(USER_AGENT), '--disable-extensions',
    '--disable-gpu', '--no-sandbox'
]
CHROMEDRIVER_PATH = 'C:/Users/asaboo/Downloads/chromedriver_76/chromedriver'
FIREFOXOPTIONS = Options()
FIREFOXOPTIONS.add_argument("--headless")


class AESOPError(Exception):
    """AESOP error."""

    pass

def _save_cookies(requests_cookiejar, filename):
    """Save cookies to a file."""
    with open(filename, 'wb') as handle:
        pickle.dump(requests_cookiejar, handle)


def _load_cookies(filename):
    """Load cookies from a file."""
    with open(filename, 'rb') as handle:
        return pickle.load(handle)


def _get_primary_status(row):
    """Get package primary status."""
    try:
        return row.find('div', {'class': 'pack_h3'}).string
    except AttributeError:
        return None


def _get_driver(driver_type):
    """Get webdriver."""
    if driver_type == 'phantomjs':
        return webdriver.PhantomJS(service_log_path=os.path.devnull)
    if driver_type == 'firefox':
        return webdriver.Firefox(firefox_options=FIREFOXOPTIONS)
    elif driver_type == 'chrome':
        chrome_options = webdriver.ChromeOptions()
        for arg in CHROME_WEBDRIVER_ARGS:
            chrome_options.add_argument(arg)
        return webdriver.Chrome(chrome_options=chrome_options)
    else:
        raise AESOPError('{} not supported'.format(driver_type))

def _login(session):
    """Login.

    Use Selenium webdriver to login. AESOP authenticates users
    in part by a key generated by complex, obfuscated client-side
    Javascript, which can't (easily) be replicated in Python.
    Invokes the webdriver once to perform login, then uses the
    resulting session cookies with a standard Python `requests`
    session.
    """
    _LOGGER.debug("attempting login")
    session.cookies.clear()
    try:
        session.remove_expired_responses()
    except AttributeError:
        pass
    try:
        driver = _get_driver(session.auth.driver)
    except WebDriverException as exception:
        raise AESOPError(str(exception))
    driver.get('https://sub.aesoponline.com/Substitute/Home')
    time.sleep (3)
    username = driver.find_element_by_id('Username')
    username.send_keys(session.auth.username)
    password = driver.find_element_by_id('Password')
    password.send_keys(session.auth.password)
    time.sleep (2)
#     driver.find_element_by_id('qa-button-login').click()
    # try:
    #     WebDriverWait(driver, LOGIN_TIMEOUT).until(
    #         EC.presence_of_element_located((By.ID, "accountBox")))
    # except TimeoutException:
    #     raise AESOPError('login failed')
    for cookie in driver.get_cookies():
        session.cookies.set(name=cookie['name'], value=cookie['value'])
    _save_cookies(session.cookies, session.auth.cookie_path)


def authenticated(function):
    """Re-authenticate if session expired."""
    def wrapped(*args):
        """Wrap function."""
        try:
            return function(*args)
        except AESOPError:
            _LOGGER.debug("attempted to access page before login")
            _LOGGER.debug(args[0])
            _login(args[0])
            return function(*args)
    return wrapped


@authenticated
def get_availjobs(session):
    """Get profile data."""
    response = session.get(LOGIN_URL, allow_redirects=False)
    # if response.status_code == 302:
    #     raise AESOPError('expired session')
    soup = BeautifulSoup(response.text, HTML_PARSER)
    _LOGGER.debug(soup.text)
    availJobs = json.loads(soup.findAll('script')[-4].text.split(',\r\n')[1].split('availJobs:')[1])
    _LOGGER.debug(availJobs)
    return availJobs

@authenticated
def get_curjobs(session):
    """Get profile data."""
    response = session.get(LOGIN_URL, allow_redirects=False)
    if response.status_code == 302:
        raise AESOPError('expired session')
    soup = BeautifulSoup(response.text, HTML_PARSER)
    curJobs = json.loads(soup.findAll('script')[-4].text.split(',\r\n')[0].split('curJobs:')[1])
    _LOGGER.debug(curJobs)
    return curJobs

# pylint: disable=too-many-arguments
def get_session(username, password, cookie_path=COOKIE_PATH, cache=True,
                cache_expiry=300, cache_path=CACHE_PATH, driver='chrome'):
    """Get session, existing or new."""
    class AESOPAuth(AuthBase):  # pylint: disable=too-few-public-methods
        """AESOP authorization storage."""

        def __init__(self, username, password, cookie_path, driver):
            """Init."""
            self.username = username
            self.password = password
            self.cookie_path = cookie_path
            self.driver = driver

        def __call__(self, r):
            """Call is no-op."""
            return r

    session = requests.Session()
    if cache:
        session = requests_cache.core.CachedSession(cache_name=cache_path,
                                                    expire_after=cache_expiry)
    session.auth = AESOPAuth(username, password, cookie_path, driver)
    session.headers.update({'User-Agent': USER_AGENT})
    if os.path.exists(cookie_path):
        _LOGGER.debug("cookie found at: %s", cookie_path)
        session.cookies = _load_cookies(cookie_path)
    else:
        _login(session)
    return session