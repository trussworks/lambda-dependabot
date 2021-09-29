import json
import sys 
import requests
import io
import re
import os

from pprint import pprint
from github import Github
from zipfile import ZipFile, Path

import logging

class StructuredLogMessage(object):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __str__(self):
        return json.dumps(self.kwargs)

m = StructuredLogMessage   # optional, to improve readability

logging.basicConfig(level=logging.INFO, format='%(message)s')

# These values should be set in the environment variables
token = os.environ['GITHUB_TOKEN'] #"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"
actor = os.environ['GITHUB_ACTOR']
workflow_name = os.environ['WORKFLOW_NAME'] # pull request workflow
#job_name = 'secret_check' # The job name
job_name = os.environ['JOB_NAME']
step_name = os.environ['STEP_NAME'] # The step name that contains the secrets check
trigger_string = os.environ['TRIGGER_STRING'] # The trigger string
log_zip = os.environ['LOG_ZIP']

def get_logs(url):
    headers = {
        'Accept': 'application/vnd.github.v3+json',
    }
    auth = ('', token)
    r = requests.get(url, headers=headers, auth=auth, allow_redirects=True)  # to get content after redirection
    logs_url = r.url # 'https://media.readthedocs.org/pdf/django/latest/django.pdf'
    with open(log_zip, 'wb') as f:
        f.write(r.content)
    #print("Stored log in", log_zip)

def zip_find_trigger():
    p = Path(log_zip)
    logpath = ''
    for path in p.iterdir():
        if path.is_dir() and job_name in path.name:
            logpath += path.name + '/'

            filep = Path(log_zip, logpath)
            for path in filep.iterdir():
                if step_name in path.name:
                    logpath += path.name
                    break
            break
    if not logpath:
        raise FileNotFoundError
    print('\nChecking logs for trigger string...', end='')
    with ZipFile(log_zip) as zf:
        with io.TextIOWrapper(zf.open(logpath), encoding="utf-8") as f:
            for line in f:
                if re.search(re.escape(trigger_string) + "$", line):
                    print('FOUND')
                    print('Logfile:', logpath)
                    print('▸', line)
                    return True #Trigger found
            print("NOT FOUND")
            return False

def get_workflow(repo):
    print("Searching workflows...", end=' ')
    workflows = repo.get_workflows()
    for wf in workflows:
        if workflow_name in wf.name:
            workflow = repo.get_workflow(wf.id)
            print("SUCCESS")
            print("Workflow id", workflow.id, ":", workflow.name)
            return workflow
    print("FAIL") 
    return None

def lambda_handler(event=None, context=None):
    # Create a github object using an access token
    g = Github(token)

    # Access a specific repo
    repo = g.get_repo('trussworks/dependabot_security_test')
    print("Repo: ", repo.name)

    workflow = get_workflow(repo)
    if not workflow:
        exit(1)

    print("\nSearching for failed runs by", actor, "...")
    message = ""
    for run in workflow.get_runs(actor=actor):
        if run.conclusion == 'failure':
            print('-------------------')
            print("▸", run.head_commit.message.split('\n')[0])
            print("Run id", run.id, "triggered by", actor)
            print("Commit:", run.head_sha[0:7])
            message = run.head_commit.message
            print("Created at:", run.created_at)

            get_logs(run.logs_url)
            
            if zip_find_trigger():
                print('Rerunning workflow')
                #result = run.rerun()
        else:
            print(run.id, run.head_commit.message.split('\n')[0], " >>", run.conclusion)
    return {
        'statusCode': 200,
        'body': json.dumps(message)
    }                    
    
if __name__ == "__main__":
    lambda_handler()