from flask import Flask, request
from touchstone_auth import TouchstoneSession
from requests import Session
from utils import MITAtlasAdapter, upload_token_to_aws
from attest import attest

url = 'https://atlas-auth.mit.edu/oauth2/authorize?client_id=50734qlesvb2p43s7ar60mh01g&response_type=code&scope=openid+profile+feature/user+covid19/user+digital-id/user+notification/user&redirect_uri=mit-atlas://login&identity_provider=Touchstone'

app = Flask(__name__)

@app.route('/login', methods=['POST'])
def login():
  session = Session()
  adapter = MITAtlasAdapter()
  session.mount('mit-atlas://', adapter)

  _ = TouchstoneSession(
    session=session,
    base_url=url,
    username=request.form['username'],
    password=request.form['password'],
    verbose=True,
    on_finish=handle_login)
  return { 'success': True }

def handle_login(request):
  token = upload_token_to_aws(request)
  attest(token)
    
if __name__ == '__main__':
  app.run(ssl_context='adhoc', port=8080)