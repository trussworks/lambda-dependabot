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


# These values should be set in the environment variables
token = os.environ['GITHUB_TOKEN']
actor = os.environ['GITHUB_ACTOR']
workflow_name = os.environ['WORKFLOW_NAME']  # pull request workflow
job_name = os.environ['JOB_NAME']
# The step name that contains the secrets check
step_name = os.environ['STEP_NAME']
trigger_string = os.environ['TRIGGER_STRING']  # The trigger string
log_zip = os.environ['LOG_ZIP']
git_repo = os.environ['GITHUB_REPO']
# What label you would like to apply to the pull on retry
pull_label = os.environ['GITHUB_PULL_LABEL']
# Set to TRUE if you want to add a comment on the pull
pull_comment = os.environ['GITHUB_ENABLE_COMMENT'].lower() in [1, '1', 'true']
# Set to true if you want the function to run but NOT trigger the rerun
dry_run = os.environ['DRY_RUN'].lower() in [1, '1', 'true']


def get_logs(url, m):
    headers = {
        'Accept': 'application/vnd.github.v3+json',
    }
    auth = ('', token)
    # This call redirects to another URL to download the content
    r = requests.get(url, headers=headers, auth=auth, allow_redirects=True)
    if r.status_code != 200:
        logging.error(m(msg='Failed to download log',
                      log_url=url, status=r.status_code))
        raise FileNotFoundError

    with open(log_zip, 'wb') as f:
        f.write(r.content)
    logging.info(m(msg="Stored log in", log_file=log_zip))


def zip_find_trigger(m):
    p = Path(log_zip)
    logpath = ''
    found = False
    for path in p.iterdir():
        if path.is_dir() and job_name in path.name:
            logpath += path.name + '/'

            filep = Path(log_zip, logpath)
            for path in filep.iterdir():
                if step_name in path.name:
                    logpath += path.name
                    found = True
                    break
            break
    if not found:
        logging.error(m(msg="Could not find logfile match",
                      job_name=job_name, step_name=step_name))
        raise FileNotFoundError

    logging.info(m(msg='Checking logs for trigger string...',
                 query=trigger_string, log_file=logpath))
    with ZipFile(log_zip) as zf:
        with io.TextIOWrapper(zf.open(logpath), encoding="utf-8") as f:
            ln = 0
            for line in f:
                ln += 1
                if re.search(re.escape(trigger_string) + "$", line):
                    logging.info(m(msg="Found trigger",
                                   log_file=logpath,
                                   log_line_number=ln,
                                   log_line=line.strip()))
                    return True  # Trigger found

            logging.info(m(msg="Trigger not found.", trigger=trigger_string))
            return False


def get_workflow(repo):
    workflows = repo.get_workflows()
    for wf in workflows:
        if workflow_name in wf.name:
            workflow = repo.get_workflow(wf.id)
            return workflow
    return None


def setup_logger():
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)
    logging.basicConfig(level=logging.INFO, format='%(message)s')


def notify_pulls(repo, pulls, workflow):
    for pull in pulls:
        if pull_label:
            pull.add_to_labels(pull_label)
        if pull_comment:
            issue = repo.get_issue(pull.number)
            issue.create_comment("Retry requested on workflow " + workflow.name +
                                 " due to missing secrets.")


def process_run(repo, workflow, run, m):
    logging.info(m(msg="Failed run found",
                   commit_title=run.head_commit.message.split('\n')[0],
                   workflow_id=workflow.id,
                   workflow_name=workflow.name,
                   run_id=run.id,
                   git_actor=actor,
                   commit_sha=run.head_sha[0:7],
                   run_created_at=str(run.created_at))
                 )

    # Download the run logs
    get_logs(run.logs_url, m)

    # If trigger is found, rerun the workflow
    if zip_find_trigger(m):
        logging.info(m(msg='Rerunning workflow',
                       workflow_id=workflow.id,
                       workflow_name=workflow.name))
        if dry_run:
            logging.info(m(msg='This is a dry run, no retry will be triggered, ' +
                           'but comments and labels will be added, if configured.'))
            result = True
        else:
            result = run.rerun()
        if result:
            notify_pulls(repo, run.pull_requests, workflow)
            return "Successful retry of workflow"
    else:
        return "No trigger string found in logs"


def response(code, msg):
    return {
        'statusCode': code,
        'body': msg
    }


def lambda_handler(event=None, context=None):
    # Create a github object using an access token
    g = Github(token)
    m = StructuredLogMessage   # Shortening function name to improve readability
    setup_logger()

    # Access a specific repo
    repo = g.get_repo(git_repo)
    if not repo:
        logging.error(m(msg="Repo not found", name=git_repo))
        return response(404, "Repo not found.")

    logging.info(m(msg="Using Repo", name=repo.name))

    # Find the correct workflow
    logging.info(m(msg="Searching workflows...", query=workflow_name))
    workflow = get_workflow(repo)
    if not workflow:
        logging.error(m(msg="Workflow not found", name=git_repo))
        return response(404, "Workflow not found.")

    logging.info(m(msg="Workflow found.", workflow_id=workflow.id,
                   workflow_name=workflow.name))

    # Search for failed runs by dependabot
    logging.info(m(msg="Searching for failed runs", query=actor))
    message = ""
    for run in workflow.get_runs(actor=actor):
        if run.conclusion == 'failure':
            try:
                message = process_run(repo, workflow, run, m)
                return response(200, message)

            except Exception as e:
                e_type, e_object, e_trace = sys.exc_info()
                filename = e_trace.tb_frame.f_code.co_filename
                line_number = e_trace.tb_lineno
                logging.error(m(msg="Exception", type=str(
                    e_type), file=filename, line=line_number))

                return response(500, "Unexpected error in run processing. Check logs.")
    return response(200, "No matching failed runs found.")


if __name__ == "__main__":
    print(lambda_handler())
