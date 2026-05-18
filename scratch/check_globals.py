import sys
sys.path.append('.')
import app

print("Globals in app:")
for name in dir(app):
    if 'creds' in name:
        print(f"- {name}: {type(getattr(app, name))}")
