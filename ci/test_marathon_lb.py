import json
import logging
import os
import re
import requests
import retrying
import shakedown

from dcos import marathon

log = logging.getLogger(__name__)
logging.basicConfig(format='[%(levelname)s] %(message)s', level='INFO')


def get_json(file_name):
    """ Retrieves json app definitions for Docker and UCR backends.
    """
    with open(file_name) as f:
        return json.load(f)


def find_app_port(config, app_name):
    """ Finds the port associated with the app in haproxy_getconfig.
    This is done through regex pattern matching.
    """
    pattern = re.search(r'{0}(.+?)\n  bind .+:\d+'.format(app_name), config)
    return pattern.group()[-5:]


@retrying.retry(stop_max_delay=10000)
def get_app_port(app_name, ip):
    """ Returns the port that the app is configured on.
    """
    get_config = requests.get(f'http://{ip}:9090/_haproxy_getconfig')
    return find_app_port(get_config.content.decode("utf-8"), app_name)


@retrying.retry(stop_max_delay=10000)
def get_app_content(app_port, ip):
    """ Returns the content of the app.
    """
    get_port = requests.get(f'http://{ip}:{app_port}')
    return (get_port.content.decode("utf-8").rstrip(), get_port.status_code)


def test_backends():
    """ Tests Marathon-lb against a number of Docker and UCR backends.
    All backends are defined in backends/ & backends_1.9/.
    The test retrieves the port to which each app is bound on.
    This is done through retrieving the port from _haproxy_getconfig.
    Each app is configured to display its id as content if launched healthy.
    The test asserts whether the text response matches the expected response.
    """

    public_ip = os.environ['PUBLIC_AGENT_IP']

    if os.environ['DCOS_VERSION'] == '1.9':
        app_defs = [
            get_json(f'backends_1.9/{filename}')
            for filename in os.listdir('backends_1.9/')
        ]

    else:
        app_defs = [
            get_json(f'backends/{filename}')
            for filename in os.listdir('backends/')
        ]


    for app_def in app_defs:
        app_id = app_def['id']

        app_name = app_id[1:] if app_id[0] == '/' else app_id
        print(app_name)
        log.info(f'{app_name} is being tested.')

        client = marathon.create_client()
        client.add_app(app_def)

        shakedown.deployment_wait(app_id=app_id)
        app = client.get_app(app_id)
        tasks = app['tasksRunning']
        instances = app_def['instances']
        assert (
            tasks == instances
        ), f"Number of tasks is {tasks}, {instances} were expected."

        log.info(f'Number of tasks for {app_name} is {tasks}')

        port = get_app_port(app_name, public_ip)
        expected_port = app_def["labels"]["HAPROXY_0_PORT"]
        msg = f"{app_name} bound to {port}, not {expected_port}."
        assert port == expected_port, msg
        log.info(f'{app_name} is bound to port {port}.')

        text_response, status_code = get_app_content(port, public_ip)
        expected_response = app_name
        msg = f"Response is {text_response}, not {expected_response}"
        if status_code == 200:
            assert text_response == expected_response, msg
        log.info(f'Text response is {text_response}.')
