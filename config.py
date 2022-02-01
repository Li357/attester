from dotenv import load_dotenv
import os

load_dotenv()

client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
atlas_uri = os.getenv('ATLAS_URI')
token_uri = os.getenv('TOKEN_URI')
redirect_uri = os.getenv('REDIRECT_URI')
auth_scope = os.getenv('AUTH_SCOPE')

aws_access_id = os.getenv('AWS_ACCESS_ID')
aws_access_key = os.getenv('AWS_ACCESS_KEY')

flask_env = os.getenv('FLASK_ENV', 'development')