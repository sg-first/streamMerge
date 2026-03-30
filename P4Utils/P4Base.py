# -*- coding: utf-8 -*-
import datetime
import subprocess
import marshal
from enum import Enum
from GUI.Color import QSLauncherColor
import sys
if sys.platform == "win32":
    from subprocess import CREATE_NO_WINDOW

class P4MgrResult(Enum):
    P4_Success = 0
    P4_ArgsError = 1
    P4_Sync_AlreadyLatest = 2
    P4_Sync_NoSuchFile = 3
    P4_Sync_CannotClobber = 4
    P4_P4CmdError = 5   # Failed to execute a P4 command because of username, port, workspace, options, etc.
    P4_Merge_NeedResolve = 6
    P4_Merge_CLInvalid = 7
    P4_Merge_NoCLInJob = 8
    P4_Merge_FilesOpenedInOhterCL = 9
    P4_Merge_Error_Partial = 10
    P4_Merge_Already_Integrated = 11
    P4_Merge_NoSuchJob = 12
    P4_Merge_CannotSubmit = 13
    P4_Merge_SuccessWithoutSubmit = 14
    P4_Merge_RuntimeError = 15
    p4_WaitingForCallback = 16
    P4_Split_Success = 17
    P4_Split_Failed = 18
    P4_Split_CLisEmpty = 19
    # TODO


class P4MergeArgs(object):
    def __init__(self,
                 cl: str = None,
                 job: str = None,
                 branch_mapping: str = None,
                 src_to_tar: str = None,
                 src_branch: str = None,
                 tar_branch: str = None,
                 auto_resolve: bool = True,
                 auto_submit: bool = False,
                 as_for_binary: bool = False,
                 update_tapd: bool = False,
                 merge_into_single_cl: bool = False,
                 merge_into_single_cl_number: str = "",
                 allow_loop: bool = True,
                 continue_when_conflict: bool = True,
                 add_pub_tag: bool = True,
                 pub_tag: str = 'pub',
                 pub_job: str = None,
                 add_comment: bool = False,
                 title_prefix: bool = False,
                 tapd_title_prefix: str = '[merged]',
                 auto_flow: bool = False,
                 obj_cl: str = None,
                 modify_cl: bool = True):
        self.cl: str = cl  # the source CL to be merged (merge by CL)
        self.job: str = job  # the job to be merged (merge by job)
        self.branch_mapping: str = branch_mapping  # the branch mapping will be used for merge (merge by branch)
        self.src_to_tar: str = src_to_tar  # the shortcuts for src_branch to tar_branch
        self.src_branch: str = src_branch  # the source branch which contains the change in the source CL
        self.tar_branch: str = tar_branch  # the target branch that the CL will merge to
        self.auto_resolve: bool = auto_resolve  # if the conflicts will be tried to resolved automatically
        self.auto_submit: bool = auto_submit  # if the CL will be submitted when no conflict needs to be resolve
        self.as_for_binary: bool = as_for_binary # for binary conflicts, accept source to merge (use p4 resolve -at) 
        self.update_tapd: bool = update_tapd  # if the TAPD title prefix etc. will be changed
        self.merge_into_single_cl: bool = merge_into_single_cl  # merge all the cl in the job to one single cl
        self.merge_into_single_cl_number: bool = merge_into_single_cl_number  # merge all the cl in the job to one single cl
        self.allow_loop: bool = allow_loop  # auto merge the next cl in the job if the prev is submitted successfully
        self.continue_when_conflict: bool = continue_when_conflict # Continue merge when conflicts arise
        self.add_pub_tag: bool = add_pub_tag  # (internal params)
        self.pub_tag: str = pub_tag  # the tag that will be added to the description of source CL
        self.pub_job: str = pub_job  # the job that the source CL will be added to
        self.add_comment: bool = add_comment  # add comment for TAPD
        self.title_prefix: bool = title_prefix  # add title prefix to TAPD
        self.tapd_title_prefix: str = tapd_title_prefix  # the prefix that will be added to the TAPD title
        self.auto_flow: bool = auto_flow  # auto flow TAPD
        self.obj_cl: str = obj_cl  # the CL number that will be merged to. (A new CL will be created in default)
        self.modify_cl: bool = modify_cl

class P4SplitArgs(object):
    def __init__(self,
                 cl: str = None,
                 src_to_tar: str = None,
                 src_branch: str = None,
                 tar_branch: str = None):
        self.cl: str = cl  # the generated CL to split
        self.src_to_tar: str = src_to_tar  # the shortcuts for src_branch to tar_branch
        self.src_branch: str = src_branch  # the source branch which contains the change in the source CL
        self.tar_branch: str = tar_branch  # the target branch that the CL will merge to

class P4ChangeListInfo(object):
    def __init__(self, user:str = "Unknow", description: str = "<enter description here>", date_time: datetime.datetime = None, cl: str = "new", client: str = "Unknow", status: str = "new", files: list = []):
        self.cl: str = cl
        self.date_time: datetime.datetime = date_time
        self.client: str = client
        self.user: str = user
        self.status: str = status
        self.description: str = description
        self.files: list = files
    
    def output(self):
        res = ""
        res += f"Change:\t{self.cl}\n\n"
        if self.date_time is not None:
            date = self.date_time.strftime('%Y/%m/%d %H:%M:%S')
            res += f"Date:\t{date}\n\n"
        res += f"Client:\t{self.client}\n\n"
        res += f"User:\t{self.user}\n\n"
        res += f"Status:\t{self.status}\n\n"
        res += f"Description:\n"
        for line in self.description.splitlines():
            res += f"\t{line}\n"
        return res

class P4JobInfo(object):
    def __init__(self, name = None, status = None, user = None, date = None, description = None):
        self.name: str = name
        self.status = status
        self.user: str = user
        self.date = date
        self.description: str = description
    
    def output(self):
        res = ""
        res += f"Job:\t{self.name}\n\n"
        res += f"Status:\t{self.status}\n\n"
        res += f"User:\t{self.user}\n\n"
        res += f"Date:\t{self.date}\n\n"
        res += f"Description:\n"
        for line in self.description.splitlines():
            res += f"\t{line}\n"
        return res
        
class P4FileInfo(object):
    def __init__(self, filename = None, action = None) -> None:
        self.filename: str = filename
        self.action: str = action
    
    def is_delete(self):
        return self.action is not None and "delete" in self.action

class P4CLIRunner(object):
    encoding = ['gbk', 'utf-8']

    def __init__(self, logger = None):
        self.logger = logger
        self.port: str = ""
        self.client: str = ""
    
    def set_p4info(self, port: str = None, client: str = None):
        if port is not None:
            self.port = port
        if client is not None:
            self.client = client

    def update(self):
        pass

    def p4_global(self, cmd: str = ""):
        p4cmd = "p4"
        p4cmd += " -Q cp936"
        if cmd != "" and cmd is not None:
            p4cmd += " " + cmd
        if self.port != "" and self.port is not None:
            p4cmd += " -p " + self.port
        if self.client != "" and self.client is not None:
            p4cmd += " -c " + self.client
        return p4cmd + " "

    def block_exec(self, cmd, args_option: list = [], args_files: list = [], input_data: str = None, timeout=20, marshal_output=False):
        file_list_text = ' '.join(args_files[:5])
        if len(args_files) > 5:
            file_list_text += ' ...(%d more items)' % (len(args_files) - 5)
        args_option_text = ' '.join(args_option)
        if len(args_files) > 30:
            temp_file_name = 'args_file_list'
            with open(temp_file_name, 'w') as f:
                f.write('\n'.join(args_files))
            cmd = '-x %s %s %s' % (temp_file_name, cmd, args_option_text)
        else:
            cmd = '%s %s %s' % (cmd, args_option_text, ' '.join(args_files))
        if not cmd.startswith(('changes', 'info', 'users', 'clients')):   # only print some important cmd
            print('p4 ' + cmd)
        if marshal_output:
            return self._p4do(cmd)
        else:
            p = subprocess.Popen(self.p4_global() + cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
            if input_data is not None:
                p.stdin.write(self.encode(input_data))
                p.stdin.close()
            try:
                out, err = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.logger.log('[P4 Manager] Time out when executing p4 command! Please check your P4 config.',
                                             color=QSLauncherColor.RedError)
                return '', 'Time out'
            return self._decode_output(out), self._decode_output(err)

    def _p4do(self, cmd):
        p = subprocess.Popen(self.p4_global("-G") + cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        _stdout = []
        try:
            while True:
                ooo = marshal.load(p.stdout)
                _stdout.append(ooo)
        except EOFError:
            pass
        p.stdout.close()

        _stderr = []
        try:
            while True:
                xxx = marshal.load(p.stderr)
                _stderr.append(xxx)
        except EOFError:
            pass
        except ValueError as e_Value:
            print(e_Value)
            print(p.stderr)

        p.stdout.close()
        return _stdout, _stderr

    def _decode_output(self, output):
        out = self.decode(output) if type(output) is bytes else output
        res = out.strip('\r\n')
        if res == '':
            return []
        else:
            return res.split('\r\n')

    def encode(self, s: str) -> bytes:
        codec = P4CLIRunner.encoding[0]
        return s.encode(codec)

    def decode(self, b: bytes) -> str:
        codec = None
        res = ''
        for codec_name in P4CLIRunner.encoding:
            try:
                res = b.decode(codec_name)
                codec = codec_name
                break
            except:
                pass

        if codec is None:
            raise Exception('Error when decoding data from P4, please report to author.')

        P4CLIRunner.encoding.remove(codec)
        P4CLIRunner.encoding.insert(0, codec)
        return res
