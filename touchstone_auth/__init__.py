"""
Implements a helper class that is responsible for logging into a
Touchstone-protected MIT SSO site. This enables programatic access
to Touchstone services by a user. No authentication flow is blocked
or bypassed; this simply allows programatic access to Duo 2FA
and Touchstone auth outside of a web browser.
"""
import enum
import json
import pathlib
import pickle
import re
from typing import Union
from xml.dom.minidom import Attr
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


from bs4 import BeautifulSoup  # type: ignore
import requests
import requests.utils

class AuthenticationError(RuntimeError):
    """Represents error with incorrect username/password"""

class TouchstoneError(RuntimeError):
    """Represents all returnable Touchstone Errors"""

class WouldBlockError(TouchstoneError):
    """Called when a 2FA blocking push is required in non-blocking mode"""

class TwofactorType(enum.Enum):
    DUO_PUSH = enum.auto()
    PHONE_CALL = enum.auto()

class TouchstoneSession:
    """
    This is a wrapper context manager class for requests.Session.
    In addition to tracking cookies across requests, a TouchstoneSession
    saves/loads the cookiejar to a file so that it is persistant across runs.
 
    In addition, this session properly logs in using Touchstone and Duo if needed.
    """
    def __init__(self,
        session:requests.Session,
        base_url:str,
        username:str,
        password:str,
        should_block:bool=True,
        twofactor_type:TwofactorType=TwofactorType.DUO_PUSH,
        verbose:bool=False,
        on_finish=None) -> None:
        """
        Creates a new Touchstone session.

        Arguments
        ---------
        base_url: a URL specifying the MIT SSO service to login to.
        pkcs12_filename: A location of a password-protected client certificate (.p12)
        pkcs12_pass: The password to the client certificate. Don't hard code this!
        cookiejar_filename: The location to persist cookies at.
        should_block: If False, if a Duo 2FA push is required, we instead raise a
            WouldBlockError. Does not error if cookies are recent enough to avoid 2FA.
        twofactor_type: The desired second factor to use for Duo authentication.
            Only Duo Push (TwofactorType.DUO_PUSH) and phone call (TwofactorType.PHONE_CALL)
            are currently supported.
        verbose: If True, extra information during log-in is printed to stdout
        wipe_domains: If not None, wipes cookies for that domain before continuing.
        """

        self._session = session
        self._base_url = base_url
        self._username = username
        self._password = password
        self._blocking = should_block
        self._twofactor_type = twofactor_type
        self._verbose = verbose
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36'
        })
        
        # Attempt to get the base URL
        initial_response = self._session.get(self._base_url)
        # Check to see the final URL to see if we have to do something
        if not initial_response.url.startswith(r'https://idp.mit.edu/idp'):
            # Attempt loading a bearer token
            self.load_bearer_token(initial_response)
            self.vlog('Logged in successfully to {} without redirecting through Touchstone'.format(
                base_url))
            return

        if initial_response.request.url is None:
            raise ValueError("initial_response.request.url is None")
        req_url: str = initial_response.request.url

        # Check which IDP page we got redirected to
        match = re.match(
            r'https:\/\/idp\.mit\.edu\/idp\/Authn\/MIT\?conversation=(.*)',
            initial_response.request.url)
        last_req = None
        if match is None:
            # Check if we need to do the SSO login now
            if (initial_response.url.startswith(r'https://idp.mit.edu/idp/profile/SAML2/Redirect/SSO') or
                initial_response.url.startswith(r'https://idp.mit.edu/idp/profile/SAML2/Unsolicited/SSO')):
                self.vlog('Touchstone cookies still up to date; performing SSO redirect.')
                last_req = self.perform_sso(initial_response)
            else:
                self.vlog('We are not in the Touchstone auth or SSO flow! Terminal URL: {}'.format(
                    initial_response.url))
                raise TouchstoneError('Invalid Touchstone state detected (not in Touchstone auth or SSO flow)')
        else:
            self.vlog('Performing certificate/Duo login...')
            touchstone_response = self.perform_touchstone(match.group(1))
            self.vlog('Performing SSO login post-Duo')
            last_req = self.perform_sso(touchstone_response)
        if not on_finish is None:
          on_finish(last_req)
          self.close()

    def load_bearer_token(self, response: requests.Response) -> None:
        """
        Attempts to load a Bearer token from the final successful redirect.
        """
        match = re.search(r".*access_token=([^&]*)&id_token=[^&]*&token_type=Bearer", response.url)
        if match is not None:
            self._session.headers.update({'authorization': 'Bearer {}'.format(match.group(1))})
            self.vlog('Bearer token loaded!')

    def perform_touchstone(self, conversation):
        """
        Performs Touchstone and Duo login procedures (handling redirects to/from Duo)

        Arguments
        ---------
        conversation: A string specifying the Touchstone conversation type.
        """
        r = self._session.get('https://idp.mit.edu/idp/Authn/UsernamePassword',params={
          'conversation': conversation,
          'j_username': self._username,
          'j_password': self._password,
        })

        duo_html = BeautifulSoup(r.text, features='html.parser')
        
        try:
          duo_script = duo_html.find(id='duo_container').findChildren('script')[1].string
        except AttributeError:
          raise AuthenticationError("Login presented wrong username and password!")

        # Clean up json string before decoding
        duo_connect_string = re.search(
            r'Duo.init\(({[\S\s]*})\);',
            duo_script).group(1).replace("'",'"')
        duo_json = json.loads(duo_connect_string)
        duo_tx, duo_app = duo_json['sig_request'].split(':')

        self.vlog('Decoded Touchstone Duo redirect request')

        # POST to Duo, which will 302 redirect, giving us the prompt SID
        duo_connect_params = {
            'tx': duo_tx,
            'parent': f'https://idp.mit.edu/idp/Authn/UsernamePassword?j_username=' + self._username + '&j_password=' + self._password + '&conversation=' + conversation,
            'v': '2.6'
        }

        auth_request = self._session.post(f"https://{duo_json['host']}/frame/web/v1/auth",
                params=duo_connect_params,
                data={
                    # Why do we have to provide tx and parent both in params and data? No idea...
                    'tx': duo_connect_params['tx'],
                    'parent': duo_connect_params['parent'],
                    'java_version': '',
                    'flash_version': '',
                    'screen_resolution_width': '1920',
                    'screen_resolution_height': '1080',
                    'color_depth': '24',
                    'is_cef_browser': 'false',
                    'is_ipad_os': 'false',
                    'is_ie_compatibility_mode': '',
                    'is_user_verifying_platform_authenticator_available': '',
                    'user_verifying_platform_authenticator_available': '',
                    'user_verifying_platform_authenticator_available_error': '',
                    'acting_ie_version': '',
                    'react_support': 'true',
                    'react_support_error_message': ''
                })
        if len(auth_request.history) > 0:
            # A redirect happened, do the full auth flow if we have time to block
            if not self._blocking:
                raise WouldBlockError('Second factor auth required, but blocking is not allowed')
            self.vlog('Second factor auth required: requested Duo auth page')

            prompt_url = auth_request.request.url
            prompt_sid = re.match(r".*\/frame\/prompt\?sid=(.*)", prompt_url).group(1)
            extra_prompt_headers = {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Referer': prompt_url,
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': f"https://{duo_json['host']}"
            }

            # POST to send the push
            factor = {
                TwofactorType.DUO_PUSH: 'Duo+Push',
                TwofactorType.PHONE_CALL: 'Phone+Call'
            }[self._twofactor_type]
            r = self._session.post(f"https://{duo_json['host']}/frame/prompt",
                    # Push data through as raw bytes; this is the correct URL encoding
                    # (don't let requests mess with it by sending as a dict)
                    data=bytes(
                        f"sid={prompt_sid}&device=phone1&factor={factor}&cookies_allowed=true&dampen_choice=true&out_of_date=&days_out_of_date=&days_to_block=None",
                        'utf-8'),
                    headers=extra_prompt_headers)

            self.vlog(f'Requested second factor authentication ({factor})')

            prompt_response = json.loads(r.text)
            if prompt_response['stat'] != 'OK':
                raise TouchstoneError("Unable to send two-factor request")

            # Do a first request (this returns the info 'Pushed a login request to your device')
            r = self._session.post(f"https://{duo_json['host']}/frame/status",
                data=bytes(f"sid={prompt_sid}&txid={prompt_response['response']['txid']}", 'utf-8'),
                headers=extra_prompt_headers)
            expected_return_status = {
                TwofactorType.DUO_PUSH: 'pushed',
                TwofactorType.PHONE_CALL: 'calling'
            }[self._twofactor_type]
            if json.loads(r.text)['response']['status_code'] != expected_return_status:
                raise TouchstoneError(f"Second-factor auth (self._twofactor_type) failed")


            # Block until the user does something with the request
            if self._twofactor_type == TwofactorType.DUO_PUSH:
                self.vlog('Successfully pushed Duo push request. Blocking until response...')
                r = self._session.post(f"https://{duo_json['host']}/frame/status",
                    data=bytes(f"sid={prompt_sid}&txid={prompt_response['response']['txid']}", 'utf-8'),
                    headers=extra_prompt_headers)
                post_prompt_response = json.loads(r.text)
                # self.vlog(post_prompt_response)
                if post_prompt_response['stat'] != 'OK':
                    raise TouchstoneError("User declined prompt or prompt timed out")

                self.vlog('Second factor auth successful!')
            elif self._twofactor_type == TwofactorType.PHONE_CALL:
                self.vlog('Successfully pushed phone call request...')
                r = self._session.post(f"https://{duo_json['host']}/frame/status",
                    data=bytes(f"sid={prompt_sid}&txid={prompt_response['response']['txid']}", 'utf-8'),
                    headers=extra_prompt_headers)
                post_request_response = json.loads(r.text)
                if (post_request_response['stat'] != 'OK' or 
                    post_request_response['response']['status_code'] != 'calling'):
                    raise TouchstoneError("Unable to call registered phone number.")
                self.vlog(post_request_response['response']['status'])
                # After the dialing response, we expect the answered response.
                r = self._session.post(f"https://{duo_json['host']}/frame/status",
                    data=bytes(f"sid={prompt_sid}&txid={prompt_response['response']['txid']}", 'utf-8'),
                    headers=extra_prompt_headers)
                post_request_response = json.loads(r.text)
                if (post_request_response['stat'] != 'OK' or 
                    post_request_response['response']['status_code'] != 'answered'):
                    raise TouchstoneError("Twofactor call declined.")
                self.vlog("Two-factor call answered. Waiting for user input...")
                # Check for successful response
                r = self._session.post(f"https://{duo_json['host']}/frame/status",
                    data=bytes(f"sid={prompt_sid}&txid={prompt_response['response']['txid']}", 'utf-8'),
                    headers=extra_prompt_headers)
                post_prompt_response = json.loads(r.text)
                if (post_prompt_response['stat'] != 'OK' or 
                    post_prompt_response['response']['status_code'] != 'allow'):
                    raise TouchstoneError("Two-factor call failed.")
                self.vlog('Second factor auth successful!')
            else:
                raise TouchstoneError('Unknown two-factor flow')

            # Get the AUTH token
            r = self._session.post(f"https://{duo_json['host']}{post_prompt_response['response']['result_url']}",
                data=bytes(f"sid={prompt_sid}", 'utf-8'),
                headers=extra_prompt_headers)
            auth_result = json.loads(r.text)
            if auth_result['stat'] != 'OK':
                raise TouchstoneError("Unable to get Touchstone auth token")
            duo_auth_info = auth_result['response']
        else:
            self.vlog('Duo push not required: extracting auth token')
            auth_html = BeautifulSoup(auth_request.text, features='html.parser')
            duo_auth_info = {
                'parent': auth_html.find('input', {'id': 'js_parent'})['value'],
                'cookie': auth_html.find('input', {'id': 'js_cookie'})['value']
            }


        self.vlog('Acquired Touchstone auth token')
        # Post back to the parent, returning the request back to use for SSO login
        return self._session.post(duo_auth_info['parent'],
            data={
                'sig_response': f"{duo_auth_info['cookie']}:{duo_app}"
            })

    def perform_sso(self, request) -> requests.Session:
        """
        Given a Request object, attempts to perform Touchstone SSO redirect by
        extracting form fields and POSTing to the right location.
        """
        touchstone_html = BeautifulSoup(request.text, features='html.parser')
        touchstone_form = touchstone_html.find('form')

        self.vlog('Posting SSO redirect')

        r = self._session.post(touchstone_form.attrs['action'], data={
            'RelayState': touchstone_form.find('input', {'name': 'RelayState'})['value'],
            'SAMLResponse': touchstone_form.find('input', {'name': 'SAMLResponse'})['value']
        })
        if r.url.startswith('https://idp.mit.edu'):
            raise TouchstoneError('SSO redirect unsuccessful')

        self.vlog('SSO redirect successful!')
        self.load_bearer_token(r)
        return r

    def vlog(self, string: str) -> None:
        """
        Logs a string to stdout if verbose is True
        """
        if self._verbose:
            print(string)

    def __enter__(self) -> requests.Session:
        """Returns the internal session when called as a context manager"""
        return self

    def close(self) -> None:
        # and close the internal session
        self._session.close()

    def __exit__(self, ex_type, value, traceback) -> Literal[False]:
        self.close()
        return False
