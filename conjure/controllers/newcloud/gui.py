from conjure.ui.views.newcloud import NewCloudView
from conjure.models.provider import Schema
from conjure import utils
from conjure import controllers
from conjure import juju
from conjure.app_config import app
import os.path as path
import yaml
import petname
import sys
from ubuntui.ev import EventLoop

this = sys.modules[__name__]
this.cloud = None


def __format_creds(creds):
    """ Formats the credentials into strings from the widgets values
    """
    formatted = {}
    for k, v in creds.items():
        if k.startswith('_'):
            # Not a widget but a private key
            k = k[1:]
            formatted[k] = v
        elif k.startswith('@'):
            # A Widget, but not stored in credentials
            continue
        else:
            formatted[k] = v.value
    return formatted


def __handle_exception(exc):
    utils.pollinate(app.session_id, 'EB')
    return app.ui.show_exception_message(exc)


def __handle_bootstrap_done(future):
    app.log.debug("handle bootstrap")
    result = future.result()
    if result.returncode > 0:
        app.log.error(result.stderr.decode())
        return __handle_exception(Exception(result.stderr.decode()))
    utils.pollinate(app.session_id, 'J004')
    EventLoop.remove_alarms()
    juju.switch(app.current_controller)


def __do_bootstrap(credential=None):
    """ We call this in two seperate places so add this for clarity
    """
    app.log.debug("Performing bootstrap: {} {}".format(
        app.current_controller, this.cloud))

    future = juju.bootstrap_async(
        controller=app.current_controller,
        cloud=this.cloud,
        credential=credential,
        exc_cb=__handle_exception)
    future.add_done_callback(
        __handle_bootstrap_done)


def __do_creds_exist():
    """ Check if credentials for existing cloud already exists so
    we can bypass the cloud config view and go straight to bootstrapping
    """
    cred_path = path.join(utils.juju_path(), 'credentials.yaml')
    if not path.isfile(cred_path):
        return False

    existing_creds = yaml.safe_load(open(cred_path))
    if 'credentials' not in existing_creds:
        return False

    if this.cloud not in existing_creds['credentials'].keys():
        return False

    return True


def finish(credentials=None, back=False):
    """ Load the Model controller passing along the selected cloud.

    Arguments:
    credentials: credentials to store for provider
    back: if true loads previous controller
    """
    if back:
        return controllers.use('clouds').render()

    cred_path = path.join(utils.juju_path(), 'credentials.yaml')
    try:
        existing_creds = yaml.safe_load(open(cred_path))
    except:
        existing_creds = {'credentials': {}}

    if this.cloud in existing_creds['credentials'].keys():
        c = existing_creds['credentials'][this.cloud]
        c[app.current_controller] = __format_creds(
            credentials)
    else:
        # Handle the case where path exists but an entry for the cloud
        # has yet to be added.
        existing_creds['credentials'][this.cloud] = {
            app.current_controller: __format_creds(
                credentials)
        }

    with open(cred_path, 'w') as cred_f:
        cred_f.write(yaml.safe_dump(existing_creds,
                                    default_flow_style=False))

    if this.cloud == 'maas':
        this.cloud = '{}/{}'.format(this.cloud,
                                    credentials['@maas-server'].value)
    utils.pollinate(app.session_id, 'CA')

    __do_bootstrap()
    return controllers.use('variants').render()


def render(cloud):
    """ Render

    Arguments:
    cloud: The cloud to create credentials for
    """

    this.cloud = cloud
    if app.current_controller is None:
        app.current_controller = petname.Name()

    # LXD is a special case as we want to make sure a bridge
    # is configured. If not we'll bring up a new view to allow
    # a user to configure a LXD bridge with suggested network
    # information.

    if this.cloud == 'localhost':
        if not utils.check_bridge_exists():
            return controllers.use('lxdsetup').render()

        app.log.debug("Found an IPv4 address, "
                      "assuming LXD is configured.")

        cloud_type = 'lxd'
        if juju.get_current_model():
            if not juju.get_model(juju.get_current_model())['type'] \
               == cloud_type:
                __do_bootstrap()
        return controllers.use('variants').render()

    # bootstrap if existing credentials are found for cloud
    if __do_creds_exist():
        try:
            creds = juju.get_credential(this.cloud, app.current_controller)
        except:
            creds = juju.get_credentials()
        if juju.get_current_model():
            if not juju.get_model(juju.get_current_model())['type'] \
               == juju.get_cloud(this.cloud)['type']:
                __do_bootstrap(list(creds[this.cloud].keys())[0])
        return controllers.use('variants').render()

    # show credentials editor otherwise
    try:
        creds = Schema[this.cloud]
    except KeyError as e:
        utils.pollinate(app.session_id, 'EC')
        return app.ui.show_exception_message(e)

    view = NewCloudView(app,
                        this.cloud,
                        creds,
                        finish)

    app.ui.set_header(
        title="New cloud setup",
    )
    app.ui.set_body(view)
