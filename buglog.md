## Bug 1: Kaggle Secrets wrong pattern
**Bug:** HF token upload failed — was using token value as key name
**Found:** Upload cell returned 401
**Fixed:** Changed to `hf_token = secrets.get_secret("HF_TOKEN")`

## Bug 2: Docker container caching old files
**Bug:** Frontend changes not reflecting after push
**Found:** UI still showing old version after multiple pushes
**Fixed:** Must push change to Dockerfile to force container rebuild, not just restart

## Bug 3: OneDrive destroying git repository
**Bug:** All local project files disappeared
**Found:** OneDrive moved files to cloud-only to free local space
**Fixed:** Moved project to C:\Projects outside OneDrive. Never store git repos inside OneDrive.