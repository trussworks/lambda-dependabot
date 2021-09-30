# Lambda Dependabot

This project is a lambda function that can be installed into AWS and configured to check your workflows and rerun any that failed because dependabot could not access secrets.

It's meant to relieve the issue discussed in this link, until Github provides a solution.

<https://github.community/t/dependabot-doesnt-see-github-actions-secrets/167104/8>

## How It Works

![How it works](images/overview.png?raw=true "How It Works")

When dependabot creates a PR, it will often fail the unit tests because the workflow cannot access secrets. A retry of the workflow by a user with permissions will allow the tests to pass.

The AWS lambda function runs every hour and checks the repo for such failed PRs. It detects a special string in the logs of the failed workflows and triggers a rerun. It outputs logs to CloudWatch for debug purposes.

It is scheduled by CloudWatch Events which can trigger it on whatever schedule the administrator prefers.

## Getting Started

### Create the Github action to detect missing secrets

First, add a github job that detects missing secrets into the workflow that is failing.

Here is an example. Instead of `MY_SECRET`, you can use an actual secret you have saved in your [Git Repo Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets).

```yaml
name: Pull Request Workflow

on:
  pull_request

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v2
      - name: Check secrets
        env: 
            MY_SECRET: "${{ secrets.MY_SECRET }}"
        run: |
          echo "SECRETS CHECK"
          if [[ -z "$MY_SECRET" ]]; then
            echo "SECRETS MISSING"
            exit 1
          else
            echo "SECRETS FOUND"
            exit 0
          fi 
        shell: bash
```

Note down the following from your workflow, which will be needed to configure the lamdba function.

```
Workflow Name: "Pull Request Workflow"
Job Name: "build"
Step Name: "Check secrets"
Trigger String: "SECRETS MISSING"
```

You should also create one access token with permissions to access this repo.
(Is there a way to make one per repo, vs per person??)

### Create an AWS Lambda function to monitor your repo

Next, create an AWS Lambda function that will check the repo for failed runs and rerun them.

1. Create a role for the lambda function.

    This gives the lambda function permissions to run and to log to CloudWatch.

    Instructions: <https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html>

    ![Create Role](images/lambda-role.png?raw=true "Lambda Role")

2. Create a lambda layer to allow use of the PyGithub package

   Go to Lambda > Layers > Create Layer

   ![Create Layer](images/create-layer.png?raw=true "Create Layer")

   Fill the the following info:

   ```text
   Name: PyGithub
   Description: Layer containing python PyGithub package
   Compatible Runtimes: Python 3.8
   ```

   Then upload the zip from this repo named `layers\pygithub.zip`

   This should create a layer you can include in your lambda function.

3. Create a lambda function to monitor your Github repo.

    Follow these instructions: <https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html>

    Once you have created a function, you can copy the code from `lambda_function.py` in this repo.

    Scroll to the bottom of the page to the layers section and click `Add a layer`.

    Add the PyGithub layer you created earlier.

4. Configure the environment variables to direct the lambda function to your repo.

    On the main Lambda function page, click on Configuration > Environment Variables

    Here are the keys and values you want to enter

    ```text
    GITHUB_ACTOR    The bot user like dependabot
    GITHUB_REPO     Your repo name with org prefix
    GITHUB_TOKEN    The access token for the repo
    WORKFLOW_NAME   Workflow name
    JOB_NAME     Job name
    STEP_NAME     Step name
    TRIGGER_STRING  Trigger string
    LOG_ZIP         Tmp zip filename, must be in /tmp
    ```

    Here's an example

    ```text
    GITHUB_ACTOR    = dependabot[bot]
    GITHUB_REPO     = trussworks/dependabot_security_test
    GITHUB_TOKEN    = #########
    WORKFLOW_NAME   = Pull Request Workflow    
    JOB_NAME        = build
    STEP_NAME       = Check secrets
    TRIGGER_STRING  = SECRETS MISSING
    LOG_ZIP         = /tmp/lambda_logs.zip
    ```

5. At this point you should be able to test the lambda function.

    Go back to the Code editor. Hit `Deploy` and after it has deployed, hit `Test`.

    It really doesn't matter what is passed in with the test, the function doesn't expect anything.

    Even if no failed dependabot runs were found, it should find the repo and the workflow.

    ```
    Test Event Name
    Basic

    Response
    {
    "statusCode": 200,
    "body": "No matching failed runs found."
    }

    Function Logs
    START RequestId: b2f783dc-a814-4d21-bbce-7f1624371660 Version: $LATEST
    {"msg": "Using Repo", "name": "dependabot_security_test"}
    {"msg": "Searching workflows...", "query": "Pull Request Workflow"}
    {"msg": "Workflow found.", "workflow_id": 13676515, "workflow_name": "Pull Request Workflow"}
    {"msg": "Searching for failed runs", "query": "dependabot[bot]"}
    END RequestId: b2f783dc-a814-4d21-bbce-7f1624371660
    REPORT RequestId: b2f783dc-a814-4d21-bbce-7f1624371660 Duration: 582.83 ms Billed Duration: 583 ms Memory Size: 128 MB Max Memory Used: 56 MB Init Duration: 310.20 ms

    Request ID
    b2f783dc-a814-4d21-bbce-7f1624371660    
    ```

### Create an AWS CloudWatch Event to trigger the lambda function on a schedule
