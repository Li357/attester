from sqlite3 import adapters
from requests.adapters import BaseAdapter
from requests.models import Response
import requests
import boto3
import base64
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

class MITAtlasAdapter(BaseAdapter):
  def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
    response = Response()
    response.status_code = 200
    response.url = request.url
    response.request = request
    response.connection = self
    return response

  def close(self):
    pass

_client_id = '50734qlesvb2p43s7ar60mh01g'
_client_secret = '1u3coerm69tm7pde33n42jse64mu3cq5cd0ab3ro98986m6167mg'
_token_url = 'https://atlas-auth.mit.edu/oauth2/token'
_redirect_uri = 'mit-atlas://login'
_scope = 'openid+profile+feature/user+covid19/user+digital-id/user+notification/user'
_access_id = 'AKIAX7XHOFA53FSZORFF'
_access_key = 'RvWKWfZzS7H4U+63uQah+/0RUAGvL9DfUAcg31vG' 
dynamodb = boto3.resource('dynamodb', aws_access_key_id=_access_id, aws_secret_access_key=_access_key, region_name='us-east-1')

def get_code_from_url(url):
  parsed = urlparse(url)
  qs = parse_qs(parsed.query)
  return qs['code'][0]

def get_authorization(client_id, client_secret):
  bytes = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8'))
  return f'Basic {str(bytes, "utf-8")}'

def get_token(code):
  res = requests.post(_token_url, headers={
    'Authorization': get_authorization(_client_id, _client_secret),
    'Content-Type': 'application/x-www-form-urlencoded',
  }, data={
    'grant_type': 'authorization_code',
    'client_id': _client_id,
    'redirect_uri': _redirect_uri,
    'scope': _scope,
    'code': code
  })
  return res.json()

def upload_token_to_aws(req):
  mit_atlas_url = req.url
  code = get_code_from_url(mit_atlas_url)
  token = get_token(code)
  token['id'] = str(uuid4())
  dynamodb.Table('AttesterRefreshTokens').put_item(Item=token)
  return token

def get_new_token(refresh_token):
  res = requests.post(_token_url, headers={
    'Authorization': get_authorization(_client_id, _client_secret),
    'Content-Type': 'application/x-www-form-urlencoded',
  }, data={
    'grant_type': 'refresh_token',
    'client_id': _client_id,
    'refresh_token': refresh_token
  })
  return res.json()

if __name__ == '__main__':
  get_token('080e9c4a-893d-4e06-81a5-0a9419884e33')