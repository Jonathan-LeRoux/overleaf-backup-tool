import json
import logging
import random

import time

import requests as reqs
import sys
from bs4 import BeautifulSoup


class OverleafClient(object):

    @staticmethod
    def filter_projects(json_content, more_attrs=None, include_archived=False):
        more_attrs = more_attrs or {}
        for p in json_content:
            # if any([p.get(status) for status in status_list]):
            if (include_archived or not p.get("archived")) and not p.get("trashed"):
                if all(p.get(k) == v for k, v in more_attrs.items()):
                    yield p

    def __init__(self, cookie=None, csrf=None):

        self._url_signin = "https://www.overleaf.com/login"
        self._dashboard_url = "https://www.overleaf.com/project"

        self._login_cookies = cookie
        self._csrf = csrf

    def all_projects(self, include_archived = False):
        """
        Get all of a user's projects with status in a given status list
        Returns: List of project objects
        """
        projects_page = reqs.get(self._dashboard_url, cookies=self._login_cookies)
        json_content = json.loads(
            BeautifulSoup(projects_page.content, 'html.parser').find('meta', {'name': 'ol-projects'})["content"])
        #".find('script', {'id': 'data'}).contents[0])
        return list(OverleafClient.filter_projects(json_content, include_archived = include_archived))

    def login_with_user_and_pass(self, username, password):
        """
        Login to the Overleaf Service with a username and a password
        Params: username, password
        Returns: Dict of cookie and CSRF
        """

        r_signing_get = reqs.get(self._url_signin)
        if r_signing_get.status_code != 200:
            err_msg = "Status code {0} when loading {1}. Can not continue...".format(r_signing_get.status_code, self._url_signin)

            raise Exception(err_msg)

        self._csrf = BeautifulSoup(r_signing_get.content, 'html.parser').find(
            'input', {'name': '_csrf'}).get('value')
        login_json = {
            "_csrf": self._csrf,
            "email": username,
            "password": password
        }
        r_signing_post = reqs.post(self._url_signin, json=login_json,
                               cookies=r_signing_get.cookies)

        is_successful = False
        login_cookies = None
        # On a successful authentication the Overleaf API returns a new authenticated cookie.
        # If the cookie is different than the cookie of the GET request the authentication was successful
        if r_signing_post.status_code == 200 and r_signing_get.cookies["overleaf_session2"] != r_signing_post.cookies[
            "overleaf_session2"]:
            is_successful = True
            login_cookies = r_signing_post.cookies

            # Enrich cookie with gke-route cookie from GET request above
            login_cookies['gke-route'] = r_signing_get.cookies['gke-route']
        else:
            err_msg = "Status code {0} when signing in {1} with user [{2}] and pass [{3}]. " \
                      "Can not continue..".format(r_signing_post.status_code, self._url_signin, username, "*" * len(password))
            raise Exception(err_msg)


        self._login_cookies = login_cookies
        return {"cookie": self._login_cookies, "csrf": self._csrf}

