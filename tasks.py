from invoke import task, Exit
import os

LAMBDA_FUNCTION = 'my-lambda-dependabot'
LAMBDA_LAYER = 'my-github-layer'

LAYERS_DIR = 'layers/'
REQUIREMENTS_FILE = 'requirements.txt'
SRC_ZIP = 'lambda_code.zip'


def _build_py_package(c, ver):
    with c.cd(LAYERS_DIR):
        c.run('mkdir -pv python/lib/{}/site-packages'.format(ver))
        cwd = os.getcwd() + '/' + c.cwd
        c.run('echo {}'.format(cwd))
        c.run('docker run -v "{cwd}":/var/task "lambci/lambda:build-{ver}" '
              '/bin/sh -c "pip install -r {req} -t python/lib/{ver}/site-packages/; exit"'.format(
                  cwd=cwd,
                  req=REQUIREMENTS_FILE,
                  ver=ver,
              ))


@task(help={"output": "Output zip (without .zip). Defaults to lambda-layer.",
            "versions": "Comma separated list of Python versions 'python3.8,python3.9'. Defaults to python3.8."})
def build_layer(c, versions='python3.8', output='lambda-layer'):
    """
    Builds python packages in a Dockerfile that closely mimics the AWS Lambda environment.

    It will create a zip that can then be published to AWS using the publish-layer command.
    """
    print("Checking requirements to build layer...".format(output))
    if not os.path.isdir(LAYERS_DIR) or not os.path.isfile(LAYERS_DIR + REQUIREMENTS_FILE):
        msg = (
            "ERROR: Couldn't find '{}'.\n"
            "Please create a requirements file at that path, including the packages you want in your layer.\n"
            .format(LAYERS_DIR + REQUIREMENTS_FILE)
        )
        raise Exit(msg)
    if os.path.isdir(LAYERS_DIR + 'python'):
        msg = (
            "ERROR: '{}' directory already exists. Please delete it.\n"
            .format(LAYERS_DIR + 'python')
        )
        raise Exit(msg)

    python_vers = versions.split(',')
    for ver in python_vers:
        print('Building packages for {}'.format(ver))
        _build_py_package(c, ver)
    with c.cd(LAYERS_DIR):
        print("Compressing files to {}.zip ...".format(LAYERS_DIR + output))
        c.run('zip -r {}.zip python'.format(output), hide='out')
        c.run('rm -rf python')
    print("Zipfile {}.zip created.".format(LAYERS_DIR + output))


@task(help={"zipfile": "Output zip. Defaults to lambda-layer.zip.",
            "name": "AWS Lambda Layer to create/publish to. Defaults to {}.".format(LAMBDA_LAYER),
            "description": "Description of layer on AWS.",
            "runtimes": "Compatible runtimes for this package 'python3.7,python3.8'."})
def publish_layer(c, name=LAMBDA_LAYER, zipfile='lambda-layer.zip', runtimes='python3.8', description=''):
    """
    Publishes the Lambda Layer to AWS. 

    If a layer with the provided name does not exist, it will create a new layer. 
    If it already exists, this command will create a new version of that layer. 

    Uses AWS cli, which should be configured to login to the appropriate account.
    """
    runtimes = runtimes.replace(',', ' ')
    if not os.path.isdir(LAYERS_DIR) or not os.path.isfile(LAYERS_DIR + zipfile):
        msg = (
            "ERROR: Couldn't find '{}'.\n"
            "Please provide the name of the zip, located in the layers directory.\n"
            .format(LAYERS_DIR + zipfile)
        )
        raise Exit(msg)
    print("Publishing zipfile {} to AWS layer {}".format(zipfile, name))
    with c.cd(LAYERS_DIR):
        c.run('aws lambda publish-layer-version '
              '--layer-name "{name}" --description "{desc}" --zip-file "fileb://{zipfile}" '
              '--compatible-runtimes {runtimes}'
              .format(name=name, desc=description, zipfile=zipfile, runtimes=runtimes))


@task(help={"name": "Lambda function to publish to. Defaults to {}.".format(LAMBDA_FUNCTION),
            "srcfile": "Python src file containing the lamdba handler. Defaults to lambda_function.py."})
def publish_code(c, name=LAMBDA_FUNCTION, srcfile="lambda_function.py"):
    """
    Publishes a new version of the lambda function to AWS.

    The lambda function must exist already. Please create it in AWS if it does not. 

    Uses AWS cli, which should be configured to login to the appropriate account.
    Note that the region you create it in must match the region you supplied in your AWS cli credentials.
    """
    if not os.path.isfile(srcfile):
        msg = (
            "ERROR: Couldn't find '{}'.\n"
            "Please provide the name of the file containing your lambda function.\n"
            .format(srcfile)
        )
        raise Exit(msg)
    print("Publishing zipped code {} to AWS lambda {}".format(srcfile, name))
    c.run('zip {zipfile} {srcfile}'.format(zipfile=SRC_ZIP, srcfile=srcfile))
    c.run('aws lambda update-function-code '
          '--function-name "{name}" --zip-file "fileb://{zipfile}" '
          .format(name=name, zipfile=SRC_ZIP))
