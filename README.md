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

### Using Invoke

Before we get started, there is an invoke script `tasks.py` included in this repo to make repetitive tasks easier. Invoke is a python package that's useful for building small cli tools.

You will need the invoke package.

```sh
pip install invoke
```

To see all the command available, use `--list` or `-l`.

```text
$ invoke -l

Available tasks:

  build-layer     Builds python packages in a Dockerfile that closely mimics the AWS Lambda environment.
  publish-code    Publishes a new version of the lambda function to AWS.
  publish-layer   Publishes the Lambda Layer to AWS.
```

To see help for a specific command use `--help <command>` or `-h <command>`.

```text
$ invoke -h publish-layer

Usage: inv[oke] [--core-opts] publish-layer [--options] [other tasks here ...]

Docstring:
  Publishes the Lambda Layer to AWS. 

  If a layer with the provided name does not exist, it will create a new layer. 
  If it already exists, this command will create a new version of that layer. 

  Uses AWS cli, which should be configured to login to the appropriate account.

Options:
  -d STRING, --description=STRING   Description of layer on AWS.
  -n STRING, --name=STRING          AWS Lambda Layer to create/publish to. Defaults to new-layer.
  -r STRING, --runtimes=STRING      Compatible runtimes for this package 'python3.7,python3.8'.
  -z STRING, --zipfile=STRING       Output zip. Defaults to lambda-layer.zip.
```

### Create the Github action to detect missing secrets

Okay let's get started. First, add a github job that detects missing secrets into the workflow that is failing. This should be **in the repo to be monitored**, not this repo.

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

#### Bot Access Token

You should also create one access token with permissions to access this repo. This is probably best done by creating a single "Bot" user with access to only this repo and then creating a personal access token for your bot.

Note down your access token you will need it later.

```text
Access Token: #######################
```

### Create an AWS Lambda function to monitor your repo

Next, create an AWS Lambda function that will check the repo for failed runs and rerun them.

1. Create a role for the lambda function.

    This gives the lambda function permissions to run and to log to CloudWatch.

    Instructions: <https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html>

    ![Create Role](images/lambda-role.png?raw=true "Lambda Role")

2. Create a lambda layer to allow use of the PyGithub package

   You can do this with the invoke tool. It will look in the layers folder for the zip.

   ```
   invoke publish-layer --zipfile = pygithub.zip
   ```

   **OR You can do it in AWS UI**

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
    JOB_NAME        Job name
    STEP_NAME       Step name
    TRIGGER_STRING  Trigger string
    LOG_ZIP         Tmp zip filename, must be in /tmp
    GITHUB_PULL_LABEL Label to add to the PR on retry. 
                    Leave blank if you don't want a label
    GITHUB_ENABLE_COMMENT Set to true to leave a comment on the PR
    DRY_RUN         If this is set to true, the actual retry will not happen, 
                    but everything else, including comments, will.
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

    If you enable `DRY_RUN` in the environment variables, the actual rerun will not occur, although comments and labels will. This allows you to test most of the flow without the retry which cannot be 'undone'.

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

Finally you want to create a CloudWatch Event to trigger the function.

You can follow these instructions here: <https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-run-lambda-schedule.html>

For your target, choose the lambda function you created above.

Done!

## Updating the Code

To update the code, you can publish it using the invoke script.

```
$ invoke publish-code

Publishing zipped code lambda_function.py to AWS lambda scan_dependabot_prs
  adding: lambda_function.py (deflated 65%)
{
    "FunctionName": "scan_dependabot_prs",
    "FunctionArn": "arn:aws:lambda:us-east-1:#########:function:scan_dependabot_prs",
    "Runtime": "python3.9",
    "Role": "arn:aws:iam::#########:role/service-role/scan_dependabot_prs-role-ycbd6y4l",
    "Handler": "lambda_function.lambda_handler",
    "CodeSize": 2560,
    "Description": "",
    "Timeout": 3,
    "MemorySize": 128,
    "LastModified": "2021-10-01T19:43:19.276+0000",
    "CodeSha256": "#########",
    "Version": "$LATEST",
    "TracingConfig": {
        "Mode": "PassThrough"
    },
    "RevisionId": "#########",
    "State": "Active",
    "LastUpdateStatus": "Successful",
    "PackageType": "Zip"
}

```

## Updating the Layer

You should not need to update the layer frequently but if you have to, you can use the invoke script.

First update `layers/requirements.txt` with the versions and packages you need.

Then build the packages locally and create a zip.

```
invoke build-layer
```

Then publish the layer

```
$ invoke publish-layer

Publishing zipfile lambda-layer.zip to AWS layer new-layer
{
    "Content": {
        "Location": "https://prod-04-2014-layers.s3.us-east-1.amazonaws.com/snapshots/#########",
        "CodeSha256": "#########=",
        "CodeSize": 3344127
    },
    "LayerArn": "arn:aws:lambda:us-east-1:#########:layer:new-layer",
    "LayerVersionArn": "arn:aws:lambda:us-east-1:#########:layer:new-layer:4",
    "Description": "None",
    "CreatedDate": "2021-10-01T19:42:36.760+0000",
    "Version": 4,
    "CompatibleRuntimes": [
        "python3.8"
    ]
}
```

Don't forget to go to your lambda function in AWS, scroll down to `Layers` and update the version being loaded.
