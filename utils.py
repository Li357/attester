from requests.adapters import BaseAdapter
from requests.models import Response
import requests
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
import base64
from urllib.parse import urlparse, parse_qs
from hashlib import sha256
import jwt
import config

class AlreadySignedUpError(RuntimeError):
  pass

class NeverSignedUpError(RuntimeError):
  pass

class MITAtlasAdapter(BaseAdapter):
  def __init__(self, username):
    super(MITAtlasAdapter, self).__init__()
    self.username = username

  def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
    response = Response()
    response.status_code = 200
    response.url = request.url
    response.request = request
    response.connection = self
    response.username = self.username
    return response

  def close(self):
    pass

dynamodb = boto3.resource(
  'dynamodb',
  aws_access_key_id=config.aws_access_id,
  aws_secret_access_key=config.aws_access_key,
  region_name='us-east-1')
table = dynamodb.Table('AttesterRefreshTokens')

def get_code_from_url(url):
  parsed = urlparse(url)
  qs = parse_qs(parsed.query)
  return qs['code'][0]

def get_authorization(client_id, client_secret):
  bytes = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8'))
  return f'Basic {str(bytes, "utf-8")}'

def get_token(code):
  res = requests.post(
    config.token_uri,
    headers={
      'Authorization': get_authorization(config.client_id, config.client_secret),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    data={
      'grant_type': 'authorization_code',
      'client_id': config.client_id,
      'redirect_uri': config.redirect_uri,
      'scope': config.auth_scope,
      'code': code
    })
  return res.json()

def sha_256(string):
  return sha256(string.encode('utf-8')).hexdigest()

def upload_token_to_aws(req):
  mit_atlas_url = req.url
  username = req.username
  code = get_code_from_url(mit_atlas_url)
  token = get_token(code)
  token['id'] = sha_256(username)

  response = table.scan(FilterExpression=Attr('id').eq(token['id']))
  if len(response['Items']) > 0:
    raise AlreadySignedUpError(token['id'])

  table.put_item(Item=token)
  return token

def get_new_token(refresh_token):
  res = requests.post(
    config.token_uri,
    headers={
      'Authorization': get_authorization(config.client_id, config.client_secret),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    data={
      'grant_type': 'refresh_token',
      'client_id': config.client_id,
      'refresh_token': refresh_token
    })
  return res.json()

def remove_from_attests(username):
  try:
    table.delete_item(Key={ 'id': sha_256(username) }, ConditionExpression=Attr('id').exists())
  except ClientError as err:
    if err.response['Error']['Code'] == 'ConditionalCheckFailedException':
      raise NeverSignedUpError
    raise err