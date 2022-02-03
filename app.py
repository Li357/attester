from flask import Flask, request, render_template, redirect, url_for
from touchstone_auth import TouchstoneSession, AuthenticationError
from requests import Session
from utils import MITAtlasAdapter, AlreadySignedUpError, NeverSignedUpError, upload_token_to_aws, remove_from_attests
from attest import attest
from werkzeug.exceptions import HTTPException
import config

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
  return render_template('index.html', error=request.args.get('error'))

@app.route('/login', methods=['POST'])
def login():
  session = Session()
  username = request.form['username']
  password = request.form['password']
  adapter = MITAtlasAdapter(username)
  session.mount('mit-atlas://', adapter)

  try:
    _ = TouchstoneSession(
      session=session,
      base_url=config.atlas_uri,
      username=username,
      password=password,
      verbose=True,
      on_finish=handle_login)
    return render_template('success.html')
  except AuthenticationError:
    return redirect(url_for('.index', error='Wrong username or password!')), 303
  except AlreadySignedUpError:
    return render_template('bruh.html')

@app.route('/remove', methods=['POST'])
def remove():
  username = request.form['username']
  try:
    remove_from_attests(username)
    return render_template('goodbye.html')
  except NeverSignedUpError:
    return redirect(url_for('.index', error=f'{username} is not signed up for automagic attests!')), 303

@app.errorhandler(Exception)
def handle_exception(err):
  if isinstance(err, HTTPException):
      return err
  print('Error!', type(err).__name__, err)
  return render_template('fail.html'), 500

def handle_login(request):
  token = upload_token_to_aws(request)
  attest(token)
    
if __name__ == '__main__':
  if config.flask_env == 'development':
    app.run(ssl_context='adhoc', port=8080)
  else:
    app.run(port=80)