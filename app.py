from flask import Flask, request, render_template
from touchstone_auth import TouchstoneSession
from requests import Session
from utils import MITAtlasAdapter, upload_token_to_aws
from attest import attest
import config

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
  return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
  session = Session()
  adapter = MITAtlasAdapter()
  session.mount('mit-atlas://', adapter)

  try:
    _ = TouchstoneSession(
      session=session,
      base_url=config.atlas_uri,
      username=request.form['username'],
      password=request.form['password'],
      verbose=True,
      on_finish=handle_login)
    return render_template('success.html', username=request.form['username'])
  except Exception as err:
    print('Error!', err)
    return render_template('fail.html'), 500

def handle_login(request):
  token = upload_token_to_aws(request)
  attest(token)
    
if __name__ == '__main__':
  if config.flask_env == 'development':
    app.run(ssl_context='adhoc', port=8080)
  else:
    app.run(port=80)