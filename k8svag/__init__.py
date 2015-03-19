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

import vagrant
import os
import time
import pickle
import subprocess
import socket
import zipfile
from tempfile import NamedTemporaryFile
from multiprocessing import Pool, cpu_count
from os import path
from cmdssh import run_cmd, remote_cmd, remote_cmd_map, run_scp
from consoleprinter import console, query_yes_no, console_warning, console_exception, console_error_exit
from arguments import Schema, Use, BaseArguments, abspath, abort, warning, unzip, download, delete_directory, info, doinput


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
        self.workingdir = None
        self.args = []
        self.localizemachine = None
        self.reload = None
        self.replacecloudconfig = None
        self.commandline = None
        self.command = None
        self.createproject = None
        doc = """
            Vagrant cluster management

            Usage:
                cryptobox vagrant [options] [--] <command> [<args>...]

            Options:
                -h --help           Show this screen.
                -p --parallel           Execute commands in parallel (ansible style).
                -v --verbose            Verbose mode.
                -f --force              Do not ask for confirmation
                -w --wait=<ws>          Wait <ws> seconds between commands.
                -d --workingdir=<wrkd>  Directory to execute commands in, default is current working dir.

            Commands:
                check                   Ansible-playbook dry-run
                clustercommand          Execute command on cluster
                createproject <name>    Create a Coreos Kubernetes cluster in local directory
                destroy                 Destroy vagrant cluster (vagrant destroy -f)
                halt                    Halt vagrant cluster (vagrant halt)
                localizemachine         Apply specific configuration for the host-machine
                ansibleplaybook         Provision server with ansible-playbook (server:playbook)
                reload                  Reload cluster (vagrant reload)
                replacecloudconfig      Replace all coreos-cloudconfigs and reboot
                ssh                     Make ssh connection into specific machine
                status                  Status of cluster or machine
                coreostoken             Print coreos token to stdout
                up <name>               Bring cluster up
                kubernetes              Kubernetes commands
        """
        self.validcommands = ["createproject", "up", "coreostoken"]
        validateschema = Schema({'command': Use(self.validcommand)})
        self.set_command_help("up", "Start all vm's in the cluster")
        super(VagrantArguments, self).__init__(doc, validateschema, parent=parent)


def set_working_dir(commandline):
    """
    @type commandline: VagrantArguments
    """
    projectname = None

    if commandline.workingdir is None:
        for tname in commandline.args:
            projectname = tname
            break

        if projectname is not None:
            answer = query_yes_no("projectname ok?: " + projectname, force=commandline.force)

            if answer == "yes":
                commandline.workingdir = abspath(os.path.join(os.getcwd(), projectname))

    if commandline.workingdir is None:
        commandline.workingdir = abspath(doinput("projectname? "))
        commandline.workingdir = abspath(os.path.join(os.getcwd(), commandline.workingdir))

    if commandline.workingdir is not None and os.path.exists(commandline.workingdir):
        desc = "workingdir: " + str(commandline.workingdir)
        info(commandline.command, desc)
    else:
        if not os.path.exists(commandline.workingdir):
            abort(commandline.command, commandline.workingdir + " does not exist")
        else:
            abort(commandline.command, "no workingdir set")

    return commandline


def header(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """
    console(b'\xe2\x9a\xaa\xef\xb8\x8f'.decode() + "  CoreOs Vagrant Kubernetes Cluster", plaintext=True, color="blue")
    console("command:", commandline.command, plaintext=True, color="grey")


def preboot_config(commandline):
    """
    @type commandline: VagrantArguments
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

    vagrantfiletemplate = os.path.join(str(commandline.workingdir), "Vagrantfile.tpl.rb")

    if not path.exists(vagrantfiletemplate):
        console_warning("no Vagrantfile in directory")
        raise SystemExit()

    if not path.exists(picklepath):
        os.mkdir(picklepath)

    func_extra_config = None
    vagranthome = commandline.workingdir
    mod_extra_config_path = path.join(vagranthome, "extra_config_vagrant.py")

    if os.path.exists(mod_extra_config_path):
        try:
            mod_extra_config = __import__(mod_extra_config_path)
            if mod_extra_config is not None:
                func_extra_config = mod_extra_config.__main__
        except ImportError:
            pass

    vmhost, provider = prepare_config(func_extra_config)
    if False is localize_config(commandline, vmhost):
        raise AssertionError("localize_config was False")

    if commandline.command in ["createproject", "localizemachine", "replacecloudconfig", "reload", "command"]:
        ntl = "configscripts/node.tmpl.yml"
        write_config_from_template(commandline, ntl, vmhost)
        ntl = "configscripts/master.tmpl.yml"
        write_config_from_template(commandline, ntl, vmhost)

        if commandline.localizemachine == 1:
            p = subprocess.Popen(["/usr/bin/vagrant", "up"], cwd=commandline.workingdir)
            p.wait()

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

        if commandline.force is True:
            default = "yes"
        else:
            default = "no"

        answerdel = query_yes_no(question="delete all files in directory?: " + name, default=default, force=commandline.force)

        if answerdel == "no":
            raise SystemExit()
        elif answerdel == "yes":
            delete_directory(name, ["master.zip"])
        else:
            ans = query_yes_no(question="reuse previous downloaded file?: " + name, force=commandline.force)

            if ans == "no":
                abort(commandline.command, "path not empty")
                raise SystemExit()
            else:
                delete_directory(name, ["master.zip"])


def download_and_unzip_k8svagrant_project(commandline, name):
    """
    @type commandline: VagrantArguments
    @type name: str
    @return: None
    """
    info(commandline.command, "downloading latest version of k8s/coreos for vagrant")
    zippath = os.path.join(name, "master.zip")

    if not os.path.exists(zippath):
        for cnt in range(1, 4):
            try:
                download("https://github.com/erikdejonge/k8svag-createproject/archive/master.zip", zippath)
                unzip("master.zip", name)
                break
            except zipfile.BadZipFile as zex:
                if cnt > 2:
                    console(zex, " - try again, attempt:", cnt, color="orange")
    else:
        try:
            unzip("master.zip", name)
        except zipfile.BadZipFile:
            try:
                download("https://github.com/erikdejonge/k8svag-createproject/archive/master.zip", zippath)
                unzip("master.zip", name)
            except zipfile.BadZipFile as zex:
                console_exception(zex)
                console_warning("could not unzip clusterfiles", print_stack=True)
                raise SystemExit()


def driver_vagrant(commandline):
    """
    @type commandline: VagrantArguments
    @return: None
    """
    if hasattr(commandline, "help") and commandline.help is True:
        return

    if commandline.command is None:
        raise AssertionError("no command set")

    if commandline.command == "createproject":
        header(commandline)
        name = None

        for tname in commandline.args:
            answer = query_yes_no("projectname ok?: " + tname, force=commandline.force)

            if answer is "yes":
                name = tname
                break
            elif answer is "no":
                break
            else:
                raise SystemExit()

        if name is None:
            name = doinput("projectname? ")

        if name:
            create_project_folder(commandline, name)
            set_working_dir(commandline)
            download_and_unzip_k8svagrant_project(commandline, name)
            provider, vmhost = preboot_config(commandline)
            console("provider:", provider)
        else:
            abort(commandline.command, "no name")

        return
    elif commandline.command == "up":
        set_working_dir(commandline)
        provider, vmhost = preboot_config(commandline)
        bring_vms_up(commandline, provider, vmhost)
    elif commandline.command == "coreostoken":
        print_coreos_token_stdout()
    else:
        abort(commandline.command, "not implemented")
        console(commandline)

# def main():
# """
#     main
#     """
#     parser = ArgumentParser(description="Vagrant controller, argument 'all' is whole cluster")
#     parser.add_argument("-s", "--ssh", dest="ssh", help="vagrant ssh", nargs='*')
#     parser.add_argument("-c", "--command", dest="command", help="execute command on cluster", nargs="*")
#     parser.add_argument("-f", "--status", dest="sshconfig", help="status of cluster or when name is given print config of ssh connections", nargs='*')
#     parser.add_argument("-u", "--up", dest="up", help="vagrant up")
#     parser.add_argument("-d", "--destroy", dest="destroy", help="vagrant destroy -f", action="store_true")
#     parser.add_argument("-k", "--halt", dest="halt", help="vagrant halt")
#     parser.add_argument("-q", "--provision", dest="provision", help="provision server with playbook (server:playybook)")
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
#     elif options.sshconfig is not None:
#         sshconfig(options)
#     elif options.command:
#         remote_command(options)
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
            l = sorted([x[0] for x in pickle.load(open(picklepath))])
            return l

        vmnames = []
        numinstances = None

        # noinspection PyBroadException
        try:
            numinstances = get_num_instances()
            osx = False

            if str(os.popen("uname -a").read()).startswith("Darwin"):
                osx = True

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
    info(commandline.command, "writing: "+config)
    open(config, "w").write(node)


def prepare_config(func_extra_config=None):
    """
    @type func_extra_config: str, unicode, None
    @return: None
    """
    vmhostosx = False
    provider = ""

    if str(os.popen("uname -a").read()).startswith("Darwin"):
        vmhostosx = True

    if not os.path.exists("/config/tokenosx.txt") or not os.path.exists("/config/tokenlinux.txt"):
        write_new_tokens(vmhostosx)



    if vmhostosx is True:
        provider = "vmware_fusion"

        if path.exists("./configscripts/setconfigosx.sh") is True:
            os.system("source ./configscripts/setconfigosx.sh")
    else:
        provider = "vmware_workstation"

        if path.exists("./configscripts/setconfiglinux.sh"):
            os.system("souce ./configscripts/setconfiglinux.sh")

    vf = open("Vagrantfile", "rt").read()
    
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
    ntl = "configscripts/master.tmpl.yml"
    write_config_from_template(commandline, ntl, vmhostosx)
    return True


def connect_ssh(options):
    """
    @type options: str, unicode
    @return: None
    """
    if len(options.ssh) == 1:
        options.ssh = options.ssh[0]
    else:
        options.ssh = 1

    index = None
    try:
        index = int(options.ssh)

        if index <= 0:
            index = 1
    except Exception as e:
        print(e)

    cnt = 0
    vmnames = get_vm_names()

    if options.ssh not in vmnames:
        for name in vmnames:
            cnt += 1

            if index is None:
                print("\033[36mssh ->", name, "\033[0m")
                cmd = "ssh core@" + name + ".a8.nl"

                while True:
                    try:
                        if run_cmd(cmd) != 0:
                            print("connection lost, trying in 1 seconds (ctrl-c to quit)")
                            time.sleep(1)
                        else:
                            break
                    except KeyboardInterrupt:
                        print()
                        break

                if options.ssh != 'all':
                    break
            else:
                if index == cnt:
                    print("ssh ->", name)
                    cmd = "ssh core@" + name + ".a8.nl"

                    while True:
                        try:
                            if run_cmd(cmd) != 0:
                                print("connection lost, trying in 1 seconds (ctrl-c to quit)")
                                time.sleep(1)
                            else:
                                break
                        except KeyboardInterrupt:
                            print()
                            break

                    if options.ssh != 'all':
                        break
        else:
            cnt = 0
            print("server", options.ssh, "not found, options are:")
            print()

            for name in vmnames:
                cnt += 1
                print(str(cnt) + ".", name)

            print()
    else:
        if options.ssh == 'all':
            print("vagrant ssh all is not possible")
        else:
            cmd = "vagrant ssh " + options.ssh
            run_cmd(cmd)


def sshconfig(options):
    """
    @type options: str, unicode
    @return: None
    """
    if len(options.sshconfig) == 1:
        options.sshconfig = options.sshconfig[0]
    else:
        options.sshconfig = "all"

    if options.sshconfig == 'all':
        vmnames = get_vm_names()

        if len(vmnames) > 0:
            for name in vmnames:
                cmd = "vagrant ssh-config " + name
                try:
                    if path.exists(".cl/" + name + ".sshconfig"):
                        out = open(".cl/" + name + ".sshconfig").read()
                    else:
                        out, eout = run_cmd(cmd, returnoutput=True)
                        out = out.strip()

                        if len(eout) == 0:
                            open(".cl/" + name + ".sshconfig", "w").write(out)

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
    else:
        cmd = "vagrant ssh-config " + options.sshconfig
        run_cmd(cmd)


def print_remote_command_result(result, lastoutput=""):
    """
    @type result: str, unicode
    @type lastoutput: str
    @return: None
    """
    if "\n" in result.strip():
        if result != lastoutput:
            print("\n\n\033[37m" + str(result), "\033[0m")
        else:
            print("same")
    else:
        if result != lastoutput:
            print("\n\n\033[37m", result, "\033[0m")
        else:
            print("same")

    return result


def remote_command(options):
    """
    @type options: str, unicode
    @return: None
    """
    server = None

    if len(options.command) == 1:
        options.command = options.command[0]
    elif len(options.command) == 2:
        server = options.command[0]
        options.command = options.command[1]
    else:
        raise AssertionError(options.command)

    if options.parallel is True:
        print("\033[36mremote\033[0m\033[32m parallel\033[0m\033[36m command:\033[0m\033[33m", options.command, "\033[0m")
    else:
        print("\033[36mremote command:\033[0m\033[33m", options.command, "\033[0m")

    if server:
        print("\033[36mon:\033[0m\033[33m", server, "\033[0m", end=' ')

    if server is None:
        vmnames = get_vm_names()

        if options.command not in vmnames:
            commands = []

            for name in vmnames:
                cmd = options.command

                if options.parallel is True:
                    commands.append((name + '.a8.nl', cmd))
                else:
                    result = remote_cmd(name + '.a8.nl', cmd)

                    if result.strip():
                        print("\033[36mon:\033[0m\033[33m", name + "\033[0m", end=' ')
                        print_remote_command_result(result)
                    else:
                        print("\033[36mon:\033[0m\033[33m", name, "\033[0m\033[36m... done\033[0m")

                    if options.wait is not None:
                        if str(options.wait) == "-1":
                            try:
                                iquit = eval(input("continue (y/n): "))

                                if iquit.strip() == "n":
                                    break
                            except KeyboardInterrupt:
                                print()
                                break
                        else:
                            time.sleep(float(options.wait))

            if len(commands) > 0:
                workers = cpu_count()

                if workers > len(commands):
                    workers = len(commands)

                expool = Pool(workers + 1)
                result = expool.map(remote_cmd_map, commands)
                lastoutput = ""

                for server, result in result:
                    if result.strip():
                        print("\033[36mon:\033[0m\033[33m", server.split(".")[0] + "\033[0m", end=' ')
                        lastoutput = print_remote_command_result(result, lastoutput)
                    else:
                        print("\033[36mon:\033[0m\033[33m", server.split(".")[0] + "\033[0m\033[36m... done\033[0m")
    else:
        cmd = options.command
        result = remote_cmd(server + '.a8.nl', cmd)

        if result:
            print_remote_command_result(result)
        else:
            print("\033[37m", "done", "\033[0m")


def bring_vms_up(options, provider, vmhostosx):
    """
    @type options: str, unicode
    @type provider: str, unicode
    @type vmhostosx: str, unicode
    @return: None
    """
    if provider is None:
        raise AssertionError("provider is None")

    run_cmd("ssh-add ~/.vagrant.d/insecure_private_key")
    run_cmd("ssh-add ./keys/secure/vagrantsecure;")
    p = subprocess.Popen(["python", "-m", "SimpleHTTPServer", "8000"], stdout=open("/dev/null", "w"), stderr=open("/dev/null", "w"))
    try:
        numinstances = None
        try:
            numinstances = get_num_instances()
        except Exception as e:
            print("ignored")
            print(e)

        allnew = False

        if options.up == 'allnew':
            allnew = True
            options.up = 'all'
            numinstances = None

        if options.up == 'all':
            if numinstances is None:
                cmd = "vagrant up"

                if allnew is True:
                    cmd += " --provision"

                cmd += " --provider=" + provider
                run_cmd(cmd)
            else:
                print("bringing up", numinstances, "instances")

                for i in range(1, numinstances + 1):
                    name = "node" + str(i)

                    if vmhostosx is True:
                        name = "core" + str(i)

                    print(name)
                    cmd = "vagrant up "
                    cmd += name

                    if allnew is True:
                        cmd += " --provision"

                    cmd += " --provider=" + provider
                    run_cmd(cmd)
        else:
            cmd = "vagrant up " + options.up + " --provider=" + provider
            run_cmd(cmd)
    finally:
        p.kill()


def destroy_vagrant_cluster():
    """
    destroy_vagrant_cluster
    """
    cmd = "vagrant destroy  -f"
    run_cmd(cmd)
    cwd = os.getcwd()
    picklepath = os.path.join(cwd, ".cl/vmnames.pickle")

    if path.exists(picklepath):
        os.remove(picklepath)
        os.system("rm -Rf .cl")

    run_cmd("rm -Rf .vagrant")

    for vmx in str(os.popen("vmrun list")):
        if ".vmx" in vmx:
            vmx = vmx.strip()
            run_cmd("vmrun stop " + vmx + " > /dev/null &")
            run_cmd("vmrun deleteVM " + vmx + " > /dev/null &")


def haltvagrantcluster(options):
    """
    @type options: str, unicode
    @return: None
    """
    if options.halt == 'all':
        cmd = "vagrant halt"
    else:
        cmd = "vagrant halt " + options.halt

    run_cmd(cmd)


def provision_ansible(options):
    """
    @type options: str, unicode
    @return: None
    """
    sp = options.provision.split(":")
    password = None
    f = NamedTemporaryFile(delete=False)

    if len(sp) > 2:
        targetvmname, playbook, password = sp
        f.write(password)
        f.seek(0)
    elif len(sp) > 1:
        targetvmname, playbook = sp
    else:
        playbook = sp[0]
        targetvmname = "all"

    print("\033[34mAnsible playbook:", playbook, "\033[0m")
    p = subprocess.Popen(["python", "-m", "SimpleHTTPServer", "8000"], stdout=open("/dev/null", "w"), stderr=open("/dev/null", "w"))
    try:
        if path.exists("./hosts"):
            vmnames = get_vm_names()

            if targetvmname == "all":
                cmd = "ansible-playbook -u core --inventory-file=" + path.join(os.getcwdu(), "hosts") + "  -u core --limit=all " + playbook

                if password is not None:
                    cmd += " --vault-password-file " + f.name

                if options.check:
                    cmd += " --check"

                run_cmd(cmd)
            else:
                for vmname in vmnames:
                    if targetvmname == vmname:
                        print("provisioning", vmname)
                        cmd = "ansible-playbook -u core -i ./hosts  -u core --limit=" + vmname + " " + playbook

                        if password is not None:
                            cmd += " --vault-password-file " + f.name

                        if options.check:
                            cmd += " --check"

                        run_cmd(cmd)
                    else:
                        print("skipping", vmname)
        else:
            run_cmd("vagrant provision")
    finally:
        p.kill()
        os.remove(f.name)


def reload_vagrant_cluster(options):
    """
    @type options: str, unicode
    @return: None
    """
    if len(options.reload) == 1:
        options.reload = options.reload[0]
    else:
        options.reload = "all"

    if options.reload == "all":
        print("reloading all")
        run_cmd("vagrant reload")
    else:
        print("stop and start", options.reload)
        run_cmd("vagrant halt -f " + str(options.reload))
        run_cmd("vagrant up " + str(options.reload))


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


def replacecloudconfig(options, vmhostosx):
    """
    @type options: argparse.Nam
    espace
    @type vmhostosx: str, unicode
    @return: None
    """
    write_new_tokens(vmhostosx)
    run_cmd("rm -f " + os.path.join(os.getcwd(), "./configscripts") + "/user-data*")
    console("Replace cloudconfiguration, checking vms are up")
    p = subprocess.Popen(["/usr/bin/vagrant", "up"], cwd=os.getcwdu())
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
            remote_cmd(name + '.a8.nl', cmd)
            print("\033[37m", name, "uploaded config, rebooting now", "\033[0m")

            if options.wait:
                print("wait: ", options.wait)

            logpath = path.join(os.getcwdu(), "logs/" + name + "-serial.txt")

            if path.exists(path.dirname(logpath)):
                open(logpath, "w").write("")

            cmd = "sudo reboot"
            remote_cmd(name + '.a8.nl', cmd)

            if options.wait is not None:
                if str(options.wait) == "-1":
                    try:
                        iquit = eval(input("\n\n---\npress enter to continue (q=quit): "))
                        if iquit.strip() == "q":
                            break

                        run_cmd("clear")
                    except KeyboardInterrupt:
                        print()
                        break
                else:
                    time.sleep(float(options.wait))

            cnt += 1


def print_coreos_token_stdout():
    """
    print_coreos_token_stdout
    """
    print("\033[36m" + str(get_token()) + "\033[0m")
