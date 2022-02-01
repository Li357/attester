import requests
import boto3
from utils import get_new_token

_attest_url = 'https://api.mit.edu/pass-v1/pass/attestations'
_access_id = 'AKIAX7XHOFA53FSZORFF'
_access_key = 'RvWKWfZzS7H4U+63uQah+/0RUAGvL9DfUAcg31vG' 
dynamodb = boto3.resource('dynamodb', aws_access_key_id=_access_id, aws_secret_access_key=_access_key, region_name='us-east-1')
table = dynamodb.Table('AttesterRefreshTokens')

def attest(token):
  print('Attesting now, id: ', token['id'])
  json_str = '{"answers":[{"id": "14","checked":false},{"id":"16","checked":true},{"id":"18","checked":false}]}'
  res = requests.post(_attest_url, headers={
    'Authorization': f'Bearer {token["access_token"]}',
    'Content-Type': 'application/json',
  }, data=json_str)
  if not res.ok:
    print('Unauthorized, getting new token!')
    new_token = get_new_token(token['refresh_token'])
    new_token['id'] = token['id']

    new_refresh_token = token['refresh_token']
    if 'refresh_token' in new_token:
      new_refresh_token = new_token['refresh_token']

    table.update_item(Key={ 'id': token['id'] }, AttributeUpdates={
      'access_token': { 'Value': new_token['access_token'], 'Action': 'PUT' },
      'id_token': { 'Value': new_token['id_token'], 'Action': 'PUT' },
      'refresh_token': { 'Value': new_refresh_token, 'Action': 'PUT' },
    })
    attest(new_token)

if __name__ == '__main__':
  response = table.scan()
  for token in response['Items']:
    attest(token)