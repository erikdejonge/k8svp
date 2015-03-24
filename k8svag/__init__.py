# !/usr/bin/env python3
# coding=utf-8
"""
Cluster management tool for setting up a coreos-vagrant cluster
25-02-15: parallel execution of ssh using paramiko
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
from __future__ import absolute_import
from builtins import super
from builtins import range
from builtins import open
from builtins import str
from builtins import input
from builtins import int
from future import standard_library
standard_library.install_aliases()
from future import standard_library
standard_library.install_aliases()

DEBUGMODE = False

# def main():
# """
#     main
#     """
#     parser = ArgumentParser(description="Vagrant controller, argument 'all' is whole cluster")
#     parser.add_argument("-s", "--ssh", dest="ssh", help="vagrant ssh", nargs='*')
#     parser.add_argument("-c", "--command", dest="command", help="execute command on cluster", nargs="*")
#     parser.add_argument("-f", "--status", dest="statuscluster", help="status of cluster or when name is given print config of ssh connections", nargs='*')
#     parser.add_argument("-u", "--up", dest="up", help="vagrant up")
#     parser.add_argument("-d", "--destroy", dest="destroy", help="vagrant destroy -f", action="store_true")
#     parser.add_argument("-k", "--halt", dest="halt", help="vagrant halt")
#     parser.add_argument("-q", "--provision", dest="provision", help="provision server with playbook (server:playbook)")
#     parser.add_argument("-r", "--reload", dest="reload", help="vagrant reload", nargs='*')
#     parser.add_argument("-a", "--replacecloudconfig", dest="replacecloudconfig", help="replacecloudconfigs and reboot", action="store_true")
#     parser.add_argument("-t", "--token", dest="token", help="print a new token", action="store_true")
#     parser.add_argument("-w", "--wait", dest="wait", help="wait between server (-1 == enter)")
#     parser.add_argument("-l", "--localizemachine", dest="localizemachine", help="apply specific configuration for a machine", nargs='*')
#     parser.add_argument("-p", "--parallel", dest="parallel", help="parallel execution", action="store_true")
#     parser.add_argument("-x", "--check", dest="check", help="ansible-playbook dry-run", action="store_true")
#     # echo "generate new token"
#     options, unknown = parser.parse_known_args()
#     if not path.exists("Vagrantfile"):
#         print("== Error: no Vagrantfile in directory ==")
#         return
#     if not path.exists(".cl"):
#         os.mkdir(".cl")
#     provider = None
#     vmhostosx = False
#     if options.localizemachine is not None:
#         options.localizemachine = list(options.localizemachine)
#         # noinspection PyTypeChecker

#         if len(options.localizemachine) == 0:
#             options.localizemachine = 1
#         else:
#             options.localizemachine = 2
#     provider, vmhostosx = localize(options, provider, vmhostosx)
#     if options.localizemachine:
#         return
#     if options.token:
#         print_coreos_token_stdout()
#     elif options.ssh is not None:
#         connect_ssh(options)
#     elif options.statuscluster is not None:
#         statuscluster(options)
#     elif options.command:
#         sshcmd_remote_command(options)
#     elif options.up:
#         bring_vms_up(options, provider, vmhostosx)
#     elif options.destroy:
#         destroy_vagrant_cluster()
#     elif options.halt:
#         haltvagrantcluster(options)
#     elif options.provision:
#         provision_ansible(options)
#     elif options.reload:
#         reload_vagrant_cluster(options)
#     elif options.replacecloudconfig:
#         replacecloudconfig(options, vmhostosx)
#     else:
#         parser.print_help()

import vagrant
import os
import re
import time
import pickle
import subprocess
import socket
import zipfile
import shutil
import netifaces
import readline
from tempfile import NamedTemporaryFile

# from multiprocessing import Pool, cpu_count

import concurrent.futures
from os import path
from cmdssh import run_cmd, remote_cmd, remote_cmd_map, run_scp, shell
from consoleprinter import console, query_yes_no, console_warning, console_exception, console_error_exit
from arguments import Schema, Use, BaseArguments, abspath, abort, warning, unzip, download, delete_directory, info, doinput
readline.parse_and_bind('tab: complete')


class VagrantArguments(BaseArguments):
    """
    MainArguments
    """
    def __init__(self, parent=None):
        """
        @type parent: str, None
        @return: None
        """
        self.force = False
        self.__workingdir = None
        self.args = []
        self.localizemachine = None
        self.reload = None
        self.replacecloudconfig = None
        self.commandline = None
        self.command = None
        self.createproject = None
        self.serial = True
        self.parallel = not self.serial
        self.wait = 0
        self.projectname = ""
        doc = """
            Vagrant cluster management

            Usage:
                cryptobox vagrant [options] [--] <command> [<projectname>] [<args>...]

            Options:
                -h --help               Show this screen.
                -s --serial             Execute commands in serial, default is parallel execution
                -v --verbose            Verbose mode.
                -f --force              Do not ask for confirmation
                -w --wait=<ws>          Wait <ws> seconds between commands.
                -d --workingdir=<wrkd>  Directory to execute commands in, default is current working dir.

            Commands:
                ansible        Provision cluster with ansible-playbook(s) [(<labelservers>:<nameplaybook>) ..]
                baseprovision  Apply configuration, createproject calls this.
                coreostoken    Print coreos token to stdout
                createproject  Create a Coreos Kubernetes cluster in local directory
                destroy        Destroy vagrant cluster (vagrant destroy -f)
                halt           Halt vagrant cluster (vagrant halt)
                reload         Reload cluster (vagrant reload)
                reset          Reset cloudconfig settings and replace on cluster, reboots cluster
                ssh            Make ssh connection into specific machine
                sshcmd         Execute command on cluster (remote command)
                status         Status of cluster or machine
                up             Bring cluster up

        """
        self.validcommands = ['ansible', 'baseprovision', 'coreostoken', 'createproject', 'destroy', 'halt', 'reload', 'replacecloudconfig', 'ssh', 'sshcmd', 'status', 'up']
        validateschema = Schema({'command': Use(self.validcommand)})
        self.set_command_help("up", "Start all vm's in the cluster")

        self.set_command_help("status", "ssh-config data combined with other data")
        self.set_command_help("ansible", "example: cbx ansible myproject all:myplaybook.yml core1:anotherplaybook.yml")

        super(VagrantArguments, self).__init__(doc, validateschema, parent=parent)

    @property
    def workingdir(self):
        """
        workingdir
        """
        return self.__workingdir

    @workingdir.setter
    def workingdir(self, v):
        """
        @type v: str
        @return: None
        """
        if self.workingdir is not None:
            raise AssertionError("workingdir was already set", self.workingdir)
        else:
            self.__workingdir = v


def driver_vagrant(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """

    if hasattr(commandline, "help") and commandline.help is True:
        return

    console("CoreOs Vagrant Kubernetes Cluster", plaintext=True, color="green")
    commandline.parallel = not commandline.serial

    if commandline.command is None:
        raise AssertionError("no command set")

    project_found, name = get_working_directory(commandline)
    if not project_found and commandline.command != "createproject":
        abort(commandline.command, "A k8svag environment is required.Run 'k8svag createproject' or \nchange to a directory with a 'Vagrantfile' and '.cl' folder in it.")
    else:
        info(commandline.command, "project '" + name + "' found in '" + os.getcwd() + "'")

    if commandline.command == "createproject":
        if project_found:
            abort(commandline.command, "project file exist, refusing overwrite")

        while True:
            answer = query_yes_no("projectname ok?: " + name, force=commandline.force)

            if answer is True:
                break
            elif answer is False:
                name = doinput("projectname?")
            else:
                raise SystemExit()

        create_project_folder(commandline, name)
        commandline = set_working_dir(commandline, name)
        gui, numinstance, memory, numcpu = input_vagrant_parameters(commandline)
        download_and_unzip_k8svagrant_project(commandline)
        try:
            configure_generic_cluster_files_for_this_machine(commandline, gui, numinstance, memory, numcpu)
        except BaseException:
            delete_directory(str(commandline.workingdir), ['master.zip'])
            raise

        run_cmd("vagrant box update")
        readytoboot = True

        if readytoboot:
            provider = get_provider()
            set_gateway_and_coreostoken(commandline)
            bring_vms_up(provider)
            info(commandline.command, "done, make sure to run 'baseprovision' after this")
        return
    elif commandline.command == "up":
        provider = get_provider()
        bring_vms_up(provider)
    elif commandline.command == "halt":
        run_cmd("vagrant halt")
    elif commandline.command == "coreostoken":
        print_coreos_token_stdout()
    elif commandline.command == "destroy":
        destroy_vagrant_cluster()
    elif commandline.command == "reload":
        run_cmd("vagrant reload")
    elif commandline.command == "status":
        run_cmd("vagrant reload")
    elif commandline.command == "replacecloudconfig":
        set_gateway_and_coreostoken(commandline)
        replacecloudconfig(commandline.wait)
    elif commandline.command == "ansible":
        playbook = None
        server = None
        password = None

        for serverplaybook in commandline.args:
            spb = serverplaybook.split(":")

            if len(spb) == 2:
                playbook = os.path.abspath(os.path.expanduser(spb[1]))
                server = spb[0].strip()
            elif len(spb) == 2:
                playbook = os.path.abspath(os.path.expanduser(spb[1]))
                server = spb[0].strip()
                password = spb[2].strip()

        if playbook and os.path.exists(playbook):
            info(commandline.command, "playbook found at " + playbook)
        else:
            warning(commandline.command, "no playbook found at " + playbook)

        if server is None:
            abort(commandline.command, "server is None")
        elif playbook is None:
            abort(commandline.command, "playbook is None")

        provision_ansible(server, playbook, password)
    elif commandline.command == "baseprovision":
        info(commandline.command, "make commands on server")
        sshcmd_remote_command("sudo mkdir /root/pypy&&sudo ln -s /home/core/bin /root/pypy/bin;", commandline.parallel)
        provision_ansible("all", "./playbooks/ansiblebootstrap.yml", None)
        password = doinput("testansible password", default="")
        provision_ansible("all", "./playbooks/testansible.yml",  password)
        vagrantsecure = os.path.join(os.getcwd(), "keys/secure/vagrantsecure")

        if os.path.exists(vagrantsecure):
            os.remove(vagrantsecure)
            os.remove(vagrantsecure + ".pub")

        run_cmd("ssh-keygen -t rsa -C \"core user vagrant\" -b 4096 -f ./vagrantsecure -N \"\"", cwd=os.path.join(os.getcwd(), "keys/secure"))
        provision_ansible("all", "./playbooks/keyswap.yml", None)
        replacecloudconfig(commandline.wait)
    elif commandline.command == "ssh":
        if len(commandline.args) != 1:
            abort(commandline.command, "No server given, [cbx vagrant ssh servername]")

        connect_ssh(str(commandline.args[0]))
    elif commandline.command == "sshcmd":

        # print(commandline)
        if len(commandline.args) == 0:
            abort(commandline.command, "no remote command entered [...vagrant <projectname> <sshcmd>]")
        try:
            sshcmd_remote_command(commandline.args[0], commandline.parallel, timeout=5)
        except socket.timeout as ex:
            abort("sshcmd: " + commandline.args[0], "exception -> " + str(ex))
    else:
        abort(commandline.command, "not implemented")
        console(commandline)


def run_commandline(parent=None):
    """
    @type parent: Arguments, None
    @return: None
    """
    commandline = VagrantArguments(parent)
    driver_vagrant(commandline)


if __name__ == "__main__":
    try:
        run_commandline()
    except KeyboardInterrupt:
        print("bye")


def set_working_dir(commandline, projectname):
    """
    @type commandline: VagrantArguments
    @type projectname: str
    @return: None
    """
    if commandline.workingdir is None:
        vagrantfile = os.path.join(os.getcwd(), "Vagrantfile.tpl.rb")

        if os.path.exists(vagrantfile):
            commandline.workingdir = os.getcwd()
            if os.path.basename(os.path.dirname(str(commandline.workingdir))) != projectname:
                console_warning(projectname, os.path.basename(os.path.dirname(str(commandline.workingdir))))
                raise AssertionError("projectname and dirname are different")

    if commandline.workingdir is None:
        if projectname is not None:
            answer = query_yes_no("workingdir ok?: " + abspath(os.path.join(os.getcwd(), projectname)), force=commandline.force)

            if answer:
                commandline.workingdir = abspath(os.path.join(os.getcwd(), projectname))

    if commandline.workingdir is not None and os.path.exists(commandline.workingdir):
        desc = "workingdir: " + str(commandline.workingdir)
        info(commandline.command, desc)
    else:
        if not os.path.exists(commandline.workingdir):
            abort(commandline.command, commandline.workingdir + " does not exist")
        else:
            abort(commandline.command, "no workingdir set")

    os.chdir(str(commandline.workingdir))
    return commandline


def input_vagrant_parameters(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """
    numcpus = 2
    gui = True
    instances = 2
    memory = 1024

    if commandline.force is False:
        numcpus = doinput("number of cpus on server (default=2)?", default=2, force=commandline.force)
        try:
            numcpus = int(numcpus)
        except ValueError:
            warning(commandline.command, "invalid input, resetting to 2")
            numcpus = 2

        gui = query_yes_no("show vm gui?", default=False, force=commandline.force)
        instances = doinput("number of server instances?", default=4, force=commandline.force)
        try:
            instances = int(instances)
        except ValueError:
            warning(commandline.command, "instances input invalid, resetting to 2")
            instances = 2

        memory = doinput("server memory in mb?", default=1024, force=commandline.force)
        try:
            memory = int(memory)
        except ValueError:
            warning(commandline.command, "memory input invalid, resetting to 1024")
            instances = 1024

    return gui, instances, memory, numcpus


def configure_generic_cluster_files_for_this_machine(commandline, gui, numinstance, memory, numcpu):
    """
    @type commandline: VagrantArguments
    @type gui: str
    @type numinstance: int
    @type memory: str
    @type numcpu: int
    @return: None
    """
    if not hasattr(commandline, "workingdir"):
        console_warning("workingdir not set")
        raise SystemExit()

    if commandline.workingdir is None:
        console_warning("workingdir is None")
        raise SystemExit()

    os.chdir(str(commandline.workingdir))
    picklepath = os.path.join(str(commandline.workingdir), ".cl")

    if not os.path.exists(picklepath):
        os.mkdir(picklepath)

    vagrantfile = os.path.join(str(commandline.workingdir), "Vagrantfile")

    if not path.exists(vagrantfile + ".tpl.rb"):
        console_warning("no Vagrantfile in directory")
        raise SystemExit()

    if not path.exists(picklepath):
        os.mkdir(picklepath)

    func_extra_config = None
    vagranthome = commandline.workingdir
    mod_extra_config_path = path.join(str(vagranthome), "extra_config_vagrant.py")

    if os.path.exists(mod_extra_config_path):
        try:
            mod_extra_config = __import__(mod_extra_config_path)
            if mod_extra_config is not None:
                func_extra_config = mod_extra_config.__main__
        except ImportError:
            pass

    vmhost, provider = prepare_config(func_extra_config)
    info(commandline.command, provider)
    if commandline.command in ["createproject", "baseprovision", "replacecloudconfig", "reload", "command"]:
        vfp = open(vagrantfile)
        vf = vfp.read()
        vfp.close()
        vf = vf.replace("cpus = x", "cpus = " + str(numcpu))
        vf = vf.replace("cpus = x", "cpus = " + str(numcpu))
        vf = vf.replace("$num_instances = x", "$num_instances = " + str(numinstance))
        vf = vf.replace("$update_channel = 'beta'", "$update_channel = 'beta'")
        vf = vf.replace("$vm_gui = x", "$vm_gui = " + str(gui).lower())
        vf = vf.replace("$vm_memory = x", "$vm_memory = " + str(memory))
        vf = vf.replace("$vm_cpus = x", "$vm_cpus = " + str(numcpu))
        open(vagrantfile, "w").write(vf)
        ntl = "configscripts/node.tmpl.yml"
        write_config_from_template(commandline, ntl, vmhost)
        ntl = "configscripts/master.tmpl.yml"
        write_config_from_template(commandline, ntl, vmhost)

    if False is localize_config(commandline, vmhost):
        raise AssertionError("localize_config was False")

    return provider, vmhost


def create_project_folder(commandline, name):
    """
    @type commandline: VagrantArguments
    @type name: str
    @return: None
    """
    info(commandline.command, "creating project: " + name)

    if not os.path.exists(name):
        os.mkdir(name)
    elif not os.path.isdir(name):
        abort(commandline.command, "workdir path is file")
        raise SystemExit()
    elif not len(os.listdir(name)) == 0:
        warning(commandline.command, "path not empty: " + name)
        answerdel = query_yes_no(question="delete all files in directory?: " + name, default=True, force=commandline.force)

        if answerdel is False:
            raise SystemExit()
        elif answerdel:
            delete_directory(name, ["master.zip"])
        else:
            ans = query_yes_no(question="reuse previous downloaded file?: " + name, force=commandline.force)

            if not ans:
                abort(commandline.command, "path not empty")
                raise SystemExit()
            else:
                delete_directory(name, ["master.zip"])


def download_and_unzip_k8svagrant_project(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """
    info(commandline.command, "downloading latest version of k8s/coreos for vagrant")
    zippath = os.path.join("master.zip")

    if not os.path.exists(zippath):
        for cnt in range(1, 4):
            try:
                download("https://github.com/erikdejonge/k8svag-createproject/archive/master.zip", zippath)
                unzip("master.zip")
                break
            except zipfile.BadZipFile as zex:
                if cnt > 2:
                    console(zex, " - try again, attempt:", cnt, color="orange")
    else:
        try:
            unzip("master.zip")
        except zipfile.BadZipFile:
            try:
                download("https://github.com/erikdejonge/k8svag-createproject/archive/master.zip", zippath)
                unzip("master.zip")
            except zipfile.BadZipFile as zex:
                console_exception(zex)
                console_warning("could not unzip clusterfiles", print_stack=True)
                raise SystemExit()


def bring_vms_up(provider):
    """
    @type provider: str, unicode
    @return: None
    """
    if provider is None:
        raise AssertionError("provider is None")

    p = subprocess.Popen(["python", "-m", "SimpleHTTPServer", "8000"], stdout=open("/dev/null", "w"), stderr=open("/dev/null", "w"))
    try:
        cmd = "vagrant up --provider=" + provider
        run_cmd(cmd)
    finally:
        p.kill()


def is_osx():
    """
    is_osx
    """
    osx = False

    if str(os.popen("uname -a").read()).startswith("Darwin"):
        osx = True

    return osx


def set_gateway_and_coreostoken(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """
    default_gateway = None
    gateways = netifaces.gateways()

    for gws in gateways:
        if gws == "default":
            for gw in gateways[gws]:
                for gw2 in gateways[gws][gw]:
                    if "." in gw2:
                        default_gateway = gw2

    if default_gateway is None:
        abort(commandline.command, "default gateway could not be found")
    else:
        info(commandline.command, "default gateway: " + default_gateway)
        to_file("config/gateway.txt", default_gateway)

    osx = is_osx()
    newtoken = get_token()

    if osx:
        to_file("config/tokenosx.txt", str(newtoken))
    else:
        to_file("config/tokenlinux.txt", str(newtoken))

    if osx:
        run_cmd("sudo vmnet-cli --stop")
        time.sleep(1)
        run_cmd("sudo vmnet-cli --start")
        time.sleep(2)
    else:
        run_cmd("sudo /usr/bin/vmware-networks --stop")
        time.sleep(1)
        run_cmd("sudo /usr/bin/vmware-networks --start")
        time.sleep(2)

    run_cmd("rm -f ~/.ssh/known_hosts")


def get_working_directory(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """
    tname = commandline.projectname
    retname = tname

    if tname is None:
        tname = os.path.basename(os.getcwd())

    if tname is not None:
        vagrantfile = os.path.join(os.path.join(os.path.dirname(os.getcwd()), str(tname)), "Vagrantfile")

        if os.path.exists(vagrantfile):
            commandline.workingdir = os.getcwd()
        else:
            vagrantfile = os.path.join(os.path.join(os.getcwd(), str(tname)), "Vagrantfile")

            if os.path.exists(vagrantfile):
                retname = tname
                commandline.workingdir = os.path.dirname(vagrantfile)
            else:
                vagrantfile = os.path.join(os.getcwd(), "Vagrantfile")

                if os.path.exists(vagrantfile):
                    if len(commandline.m_argv) > 0:
                        commandline.args.append(commandline.m_argv[-1:][0])

                    retname = os.path.basename(os.path.dirname(vagrantfile))
                    commandline.projectname = retname
                    commandline.workingdir = os.path.dirname(vagrantfile)

    project_found = commandline.workingdir is not None
    if project_found is True:
        os.chdir(str(commandline.workingdir))
        retname = os.path.basename(str(commandline.workingdir))

    if retname is None:
        retname = "?"

    return project_found, retname


def get_num_instances():
    """
    get_num_instances
    """
    v = open("Vagrantfile").read()
    numinstances = int(v[v.find("num_instances") + (v[v.find("num_instances"):].find("=")):].split("\n")[0].replace("=", "").strip())
    return numinstances


def get_vm_names(retry=False):
    """
    @type retry: str, unicode
    @return: None
    """
    try:
        cwd = os.getcwd()
        picklepath = os.path.join(cwd, ".cl/vmnames.pickle")

        if not os.path.exists(os.path.join(cwd, "Vagrantfile")):
            return []

        if path.exists(picklepath):
            l = sorted([x[0] for x in pickle.load(open(picklepath, "rb"))])
            return l

        vmnames = []
        numinstances = None

        # noinspection PyBroadException #                  #                 #                 ^ pycharm d1rect1ve 0
        try:
            numinstances = get_num_instances()
            osx = is_osx()

            for i in range(1, numinstances + 1):
                if osx is True:
                    vmnames.append(["core" + str(i), None])
                else:
                    vmnames.append(["node" + str(i), None])

        except Exception as e:
            print("\033[31m", e, "\033[0m")

        if numinstances is None:
            v = vagrant.Vagrant()
            status = v.status()

            for vm in status:
                vmname = vm.name.split(" ")[0].strip()
                vmnames.append([vmname, v.conf(v.ssh_config(vm_name=vmname))])

        if len(vmnames) > 0:
            pickle.dump(vmnames, open(picklepath, "wb"))

        l = sorted([x[0] for x in vmnames])
        return l
    except subprocess.CalledProcessError:
        if retry:
            return []

        return get_vm_names(True)


def get_vm_configs():
    """
    get_vm_configs
    """
    cwd = os.getcwd()
    picklepath = os.path.join(cwd, ".cl/vmnames.pickle")
    get_vm_names()
    result = [x[1] for x in pickle.load(open(picklepath)) if x[1] is not None]

    if len(result) > 0:
        return result
    else:
        v = vagrant.Vagrant()
        status = v.status()
        vmnames = []

        for vm in status:
            vmname = vm.name.split(" ")[0].strip()
            vmnames.append([vmname, v.conf(v.ssh_config(vm_name=vmname))])

        if len(vmnames) > 0:
            picklepath = os.path.join(cwd, ".cl/vmnames.pickle")
            pickle.dump(vmnames, open(picklepath, "wb"))

        return [x[1] for x in vmnames if x[1] is not None]


def get_token():
    """
    get_token
    """
    token = os.popen("curl -s https://discovery.etcd.io/new ").read()
    cnt = 0

    while "Unable" in token:
        if cnt > 3:
            raise AssertionError("could not fetch token")

        time.sleep(1)
        token = os.popen("curl -s https://discovery.etcd.io/new ").read()
        cnt += 1

    return token


def write_config_from_template(commandline, ntl, vmhostosx):
    """
    @type commandline: VagrantArguments
    @type ntl: str, unicode
    @type vmhostosx: bool
    @return: None
    """
    node = open(ntl).read()

    if vmhostosx:
        masterip = "192.168.14.41"
        node = node.replace("<master-private-ip>", masterip)
        node = node.replace("<name-node>", "core1.a8.nl")
    else:
        masterip = "192.168.14.51"
        node = node.replace("<master-private-ip>", masterip)
        node = node.replace("<name-node>", "node1.a8.nl")

    info(commandline.command, "master-private-ip: " + masterip)
    config = ntl.replace(".tmpl", "")
    info(commandline.command, "writing: " + config)
    open(config, "w").write(node)


def sed(oldstr, newstr, infile):
    """
    @type oldstr: str
    @type newstr: str
    @type infile: str
    @return: None
    """
    linelist = []
    with open(infile) as f:
        for item in f:
            newitem = re.sub(oldstr, newstr, item)
            linelist.append(newitem)
    with open(infile, "w") as f:
        f.truncate()

        for line in linelist:
            f.writelines(line)


def to_file(fpath, txt, mode="wt"):
    """
    @type fpath: str
    @type txt: str
    @type mode: str
    @return: None
    """
    with open(fpath, mode) as f:
        f.write(txt)


def cat(fpath, mode="rt"):
    """
    @type fpath: str
    @type mode: str
    @return: None
    """
    with open(fpath, mode) as f:
        return f.read()


def cp(fpathin, fpathout):
    """
    @type fpathin: str
    @type fpathout: str
    @return: None
    """
    shutil.copyfile(fpathin, fpathout)


def echo(content, fpathout):
    """
    @type content: str
    @type fpathout: str
    @return: None
    """
    to_file(fpathout, content)


def host_osx():
    """
    host_osx
    """
    vmhostosx = False

    if str(os.popen("uname -a").read()).startswith("Darwin"):
        vmhostosx = True

    return vmhostosx


def get_provider():
    """
    get_provider
    """
    if host_osx():
        provider = "vmware_fusion"
    else:
        provider = "vmware_workstation"

    return provider


def prepare_config(func_extra_config=None):
    """
    @type func_extra_config: str, unicode, None
    @return: None
    """
    vmhostosx = host_osx()

    if not os.path.exists("/config/tokenosx.txt") or not os.path.exists("/config/tokenlinux.txt"):
        write_new_tokens(vmhostosx)

    cp("Vagrantfile.tpl.rb", "Vagrantfile")

    if vmhostosx is True:
        provider = get_provider()
        cp("./roles/coreos-bootstrap/files/bootstraposx.txt", "./roles/coreos-bootstrap/files/bootstrap.sh")
        echo("192.168.14.4", "./config/startip.txt")
        echo("core", "./config/basehostname.txt")
        echo("f294d901-f14b-4370-9a43-ddb2cdb1ad02", "./config/updatetoken.txt")
        cp("./config/tokenosx.txt", "./config/token.txt")
        sed("node", "core", "Vagrantfile")
        sed("core.yml", "node.yml", "Vagrantfile")
    else:
        provider = get_provider()
        cp("./roles/coreos-bootstrap/files/bootstraplinux.txt", "./roles/coreos-bootstrap/files/bootstrap.sh")
        echo("192.168.14.5", "./config/startip.txt")
        echo("node", "./config/basehostname.txt")
        echo("3a1f12c5-de6a-4ca9-9357-579598038cd8", "./config/updatetoken.txt")
        cp("./config/tokenlinux.txt", "./config/token.txt")

    if func_extra_config:
        func_extra_config()

    if provider == "":
        console_error_exit("no provider set")

    retval = (vmhostosx, provider)
    return retval


def localize_config(commandline, vmhostosx):
    """
    @type commandline: VagrantArguments
    @type vmhostosx: bool
    @return: None
    """
    run_cmd('rm -Rf ".cl"')
    run_cmd('rm -Rf "hosts"')

    if not os.path.exists(".cl"):
        os.mkdir(".cl")

    if vmhostosx is True:
        info(commandline.command, "Localized for OSX")
    else:
        info(commandline.command, "Localized for Linux")

    hosts = open("hosts", "w")

    # for cf in get_vm_configs():
    # hosts.write(cf["Host"] + " ansible_ssh_host=" + cf["HostName"] + " ansible_ssh_port=22\n")
    vmnames = get_vm_names()

    for name in vmnames:
        try:
            hostip = str(socket.gethostbyname(name + ".a8.nl"))
            hosts.write(name + " ansible_ssh_host=" + hostip + " ansible_ssh_port=22\n")
        except socket.gaierror:
            hosts.write(name + " ansible_ssh_host=" + name + ".a8.nl ansible_ssh_port=22\n")

    hosts.write("\n[masters]\n")

    for name in vmnames:
        hosts.write(name + "\n")
        break

    cnt = 0
    hosts.write("\n[etcd]\n")

    for name in vmnames:
        if cnt == 1:
            hosts.write(name + "\n")

        cnt += 1

    cnt = 0
    hosts.write("\n[nodes]\n")

    for name in vmnames:
        if cnt > 0:
            hosts.write(name + "\n")

        cnt += 1

    hosts.write("\n[all]\n")

    for name in vmnames:
        hosts.write(name + "\n")

    hosts.write("\n[all_groups:children]\nmasters\netcd\nnodes\n")
    hosts.write("\n[coreos]\n")

    for name in vmnames:
        hosts.write(name + "\n")

    hosts.write("\n[coreos:vars]\n")
    hosts.write("ansible_ssh_user=core\n")
    hosts.write("ansible_python_interpreter=\"PATH=/home/core/bin:$PATH python\"\n")
    hosts.flush()
    hosts.close()
    cwd = os.getcwd()
    ntl = os.path.join(cwd, "configscripts/node.tmpl.yml")

    if not os.path.exists(ntl):
        console_error_exit("configscripts/node.tmpl.yml not found", print_stack=True)

    write_config_from_template(commandline, ntl, vmhostosx)
    ntl = os.path.join(cwd, "configscripts/master.tmpl.yml")

    if not os.path.exists(ntl):
        console_error_exit("configscripts/master.tmpl.yml not found", print_stack=True)

    write_config_from_template(commandline, ntl, vmhostosx)
    return True


def connect_ssh(server):
    """
    @type server: str
    @return: None
    """
    cnt = 0
    vmnames = get_vm_names()

    if server not in vmnames:
        try:
            index = int(server)
        except ValueError:
            index = None

    if server not in vmnames:
        for name in vmnames:
            cnt += 1

            if index is None:
                print("\033[36mssh ->", name, "\033[0m")
                cmd = "ssh core@" + name + ".a8.nl"

                while True:
                    try:
                        if shell(cmd) != 0:
                            print("connection lost, trying in 1 seconds (ctrl-c to quit)")
                            time.sleep(1)
                        else:
                            break
                    except KeyboardInterrupt:
                        print()
                        break

                if server != 'all':
                    break
            else:
                if index == cnt:
                    print("ssh ->", name)
                    cmd = "ssh core@" + name + ".a8.nl"

                    while True:
                        try:
                            if shell(cmd) != 0:
                                print("connection lost, trying in 1 seconds (ctrl-c to quit)")
                                time.sleep(1)
                            else:
                                break
                        except KeyboardInterrupt:
                            print()
                            break

                    if server != 'all':
                        break
        else:
            info("ssh", "server " + server + " not found, options are:")
            answers = []

            for name in vmnames:
                answers.append(name)

            inputserver = doinput("enter number", answers=answers)
            cmd = "vagrant ssh " + inputserver
            shell(cmd)
    else:
        if server == 'all':
            print("vagrant ssh all is not possible")
        else:
            cmd = "vagrant ssh " + server
            shell(cmd)


def statuscluster():
    """
    statuscluster
    """
    vmnames = get_vm_names()

    if len(vmnames) > 0:
        for name in vmnames:
            cmd = "vagrant ssh-config " + name
            try:
                if path.exists(".cl/" + name + ".statuscluster"):
                    out = open(".cl/" + name + ".statuscluster").read()
                else:
                    out, eout = run_cmd(cmd, returnoutput=True)
                    out = out.strip()

                    if len(eout) == 0:
                        open(".cl/" + name + ".statuscluster", "w").write(out)

                res = ""

                for row in out.split("\n"):
                    if "HostName" in row:
                        res = row.replace("HostName", "").strip()

                result = remote_cmd(name + '.a8.nl', 'cat /etc/os-release|grep VERSION_ID')

                if len(res.strip()) > 0:
                    print("\033[32m", name, res.strip(), "up", result.lower().strip(), "\033[0m")
                else:
                    print("\033[31m", name, "down", "\033[0m")
            except subprocess.CalledProcessError:
                print("\033[31m", name, "down", "\033[0m")
    else:
        run_cmd("vagrant status")


def print_sshcmd_remote_command_result(result, lastoutput=""):
    """
    @type result: str, unicode
    @type lastoutput: str
    @return: None
    """
    if result != lastoutput:
        console(result, color="darkgreen", plainprint=True)
    else:
        console("same", color="darkgreen", plainprint=True)

    return result


def sshcmd_remote_command(command, parallel, wait=False, server=None, timeout=60):
    """
    @type command: str
    @type parallel: bool
    @type wait: bool
    @type server: None, str
    @type timeout: int
    @return: None
    """
    if parallel is True:
        info(command, "execute parallel")

    if server is not None:
        info(command, "on server " + server)

    if server is None:
        vmnames = get_vm_names()

        if command not in vmnames:
            commands = []

            for name in vmnames:
                cmd = command

                if parallel is True:
                    commands.append((name + '.a8.nl', cmd, 'core'))
                else:
                    result = remote_cmd(name + '.a8.nl', cmd, timeout=timeout, username='core')

                    if result.strip():
                        info(command, "on server " + name)
                        print_sshcmd_remote_command_result(result)
                    else:
                        info(command, "on server " + name + "...done")

                    if wait is not None:
                        if str(wait) == "-1":
                            try:
                                iquit = eval(input("continue (y/n): "))

                                if iquit.strip() == "n":
                                    break
                            except KeyboardInterrupt:
                                print()
                                break
                        else:
                            time.sleep(float(wait))

            if len(commands) > 0:
                # workers = cpu_count()
                # if workers > len(commands):
                #    workers = len(commands)
                # expool = Pool(workers + 1)
                with concurrent.futures.ProcessPoolExecutor(max_workers=8) as executor:
                    result = executor.map(remote_cmd_map, commands)

                # result = expool.map(remote_cmd_map, commands)
                    lastoutput = ""

                    for server, result in result:
                        if result.strip():
                            warning(command, server.split(".")[0])
                            lastoutput = print_sshcmd_remote_command_result(result, lastoutput)
                        else:
                            warning(command, server.split(".")[0] + "... done")
    else:
        cmd = command
        result = remote_cmd(server + '.a8.nl', cmd, username='core')

        if result:
            print_sshcmd_remote_command_result(result)


def destroy_vagrant_cluster():
    """
    destroy_vagrant_cluster
    """
    cwd = os.getcwd()
    try:
        cmd = "vagrant destroy -f"
        run_cmd(cmd)

        for vmx in str(os.popen("vmrun list")):
            if ".vmx" in vmx:
                vmx = vmx.strip()
                run_cmd("vmrun stop " + vmx + " > /dev/null &")
                run_cmd("vmrun deleteVM " + vmx + " > /dev/null &")

    finally:
        os.chdir(os.path.dirname(cwd))
        shutil.rmtree(cwd)


def provision_ansible(targetvmname, playbook, password):
    """
    @type targetvmname: str
    @type playbook: str
    @type password: str, None
    @return: None
    """
    f = NamedTemporaryFile(delete=False, mode="w+t")

    if password is not None:
        f.write(password)
        f.seek(0)

    print("\033[34mAnsible playbook:", playbook, "\033[0m")
    p = subprocess.Popen(["python", "-m", "SimpleHTTPServer", "8000"], stdout=open("/dev/null", "w"), stderr=open("/dev/null", "w"))
    try:
        if path.exists("./hosts"):
            vmnames = get_vm_names()

            if targetvmname == "all":
                cmd = "ansible-playbook -u core --inventory-file=" + path.join(os.getcwd(), "hosts") + "  -u core --limit=all " + playbook

                if password is not None:
                    cmd += " --vault-password-file " + f.name
                run_cmd(cmd, prefix=targetvmname + ":" + playbook)
            else:
                for vmname in vmnames:
                    if targetvmname == vmname:
                        print("provisioning", vmname)
                        cmd = "ansible-playbook -u core -i ./hosts  -u core --limit=" + vmname + " " + playbook

                        if password is not None:
                            cmd += " --vault-password-file " + f.name
                        run_cmd(cmd, prefix=targetvmname + ":" + playbook)
                    else:
                        print("skipping", vmname)
        else:
            run_cmd("vagrant provision")
    finally:
        p.kill()
        os.remove(f.name)


def write_new_tokens(vmhostosx):
    """
    @type vmhostosx: bool
    @return: None
    """
    token = get_token()

    def tokenpath(arch):
        """
        @type arch: str
        @return: None
        """
        cwd = os.getcwd()
        configpath = os.path.join(cwd, "config")

        if not os.path.exists(configpath):
            os.mkdir(configpath)

        path2 = os.path.join(cwd, "config/token" + arch + ".txt")
        return path2

    if vmhostosx is True:
        tposx = tokenpath("osx")
        open(tposx, "w").write(token)
    else:
        tlin = tokenpath("linux")
        open(tlin, "w").write(token)


def replacecloudconfig(wait):
    """
    @type wait: int
    @return: None
    """
    vmhostosx = is_osx()
    write_new_tokens(vmhostosx)
    run_cmd("rm -f " + os.path.join(os.getcwd(), "./configscripts") + "/user-data*")
    console("Replace cloudconfiguration, checking vms are up")
    p = subprocess.Popen(["/usr/bin/vagrant", "up"], cwd=os.getcwd())
    p.wait()
    vmnames = get_vm_names()
    knownhosts = path.join(path.join(path.expanduser("~"), ".ssh"), "known_hosts")

    if path.exists(knownhosts):
        os.remove(knownhosts)

    if len(vmnames) > 0:
        cnt = 1

        for name in vmnames:

            # rsa_private_key = path.join(os.getcwd(), "keys/secure/vagrantsecure")
            run_scp(server=name + '.a8.nl', cmdtype="put", fp1="configscripts/user-data" + str(cnt) + ".yml", fp2="/tmp/vagrantfile-user-data", username="core")
            cmd = "sudo cp /tmp/vagrantfile-user-data /var/lib/coreos-vagrant/vagrantfile-user-data"
            remote_cmd(name + '.a8.nl', cmd, username='core')
            print("\033[37m", name, "uploaded config, rebooting now", "\033[0m")

            if wait:
                print("wait: ", wait)

            logpath = path.join(os.getcwd(), "logs/" + name + "-serial.txt")

            if path.exists(path.dirname(logpath)):
                open(logpath, "w").write("")

            cmd = "sudo reboot"
            remote_cmd(name + '.a8.nl', cmd, username='core')

            if wait is not None:
                if str(wait) == "-1":
                    try:
                        iquit = eval(input("\n\n---\npress enter to continue (q=quit): "))
                        if iquit.strip() == "q":
                            break

                        run_cmd("clear")
                    except KeyboardInterrupt:
                        print()
                        break
                else:
                    time.sleep(float(wait))

            cnt += 1


def print_coreos_token_stdout():
    """
    print_coreos_token_stdout
    """
    print("\033[36m" + str(get_token()) + "\033[0m")
