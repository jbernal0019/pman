#!/usr/bin/env python3.5

# -*- coding: utf-8 -*-
"""


 _ __  _ __ ___   __ _ _ __
| '_ \| '_ ` _ \ / _` | '_ \
| |_) | | | | | | (_| | | | |
| .__/|_| |_| |_|\__,_|_| |_|
| |
|_|


font generated by:
http://patorjk.com/software/taag/#p=display&f=Doom&t=pman

This module implements a server side job controller/manager
for systems that need to track jobs/processes via a simple
socket interface.

"""
from __future__ import print_function

import  abc
import  json
import  sys
import  datetime
import  time
import  os

import  threading
import  zmq
import  json
# from    urllib      import  urlparse
from    urllib.parse    import  urlparse
import  argparse
import  datetime
from    webob           import  Response
import  psutil
import  uuid

import  queue
from    functools       import  partial
import  inspect
import  crunner
import  logging

import  C_snode
import  message
from    _colors         import  Colors

logging.basicConfig(level=logging.DEBUG,
                    format='(%(threadName)-10s) %(message)s')

class debug(object):
    """
        A simple class that provides some helper debug functions. Mostly
        printing function/thread names and checking verbosity level
        before printing.
    """

    def __init__(self, **kwargs):
        """
        Constructor
        """

        self.verbosity  = 0
        self.level      = 0

        for k, v in kwargs.items():
            if k == 'verbosity':    self.verbosity  = v
            if k == 'level':        self.level      = v

    def __call__(self, *args, **kwargs):
        self.print(*args, **kwargs)

    def print(self, *args, **kwargs):
        """
        The "print" command for this object.

        :param kwargs:
        :return:
        """

        self.level  = 0
        self.msg    = ""

        for k, v in kwargs.items():
            if k == 'level':    self.level  = v
            if k == 'msg':      self.msg    = v

        if len(args):
            self.msg    = args[0]

        if self.level <= self.verbosity:

            print('%26s | %50s | %30s | ' % (
                datetime.datetime.now(),
                threading.current_thread(),
                inspect.stack()[1][3]
            ), end='')
            for t in range(0, self.level): print("\t", end='')
            print(self.msg)


class pman(object):
    """
    The server class for the pman (process manager) server

    """
    __metaclass__   = abc.ABCMeta


    def log(self, *args):
        """
        get/set the internal pman log message object.

        Caller can further manipulate the log object with object-specific
        calls.
        """
        if len(args):
            self._log = args[0]
        else:
            return self._log

    def name(self, *args):
        """
        get/set the descriptive name text of this object.
        """
        if len(args):
            self.__name = args[0]
        else:
            return self.__name

    def col2_print(self, str_left, str_right):
        print(Colors.WHITE +
              ('%*s' % (self.LC, str_left)), end='')
        print(Colors.LIGHT_BLUE +
              ('%*s' % (self.RC, str_right)) + Colors.NO_COLOUR)

    def __init__(self, **kwargs):
        """

        """


        self.debug              = message.Message(logTo = './debug.log')
        self.debug._b_syslog    = True
        self._log               = message.Message()
        self._log._b_syslog     = True
        self.__name             = "pman"

        self._name              = ""
        self.within             = None                      # An encapsulating object

        # DB
        self.str_DBpath         = '/tmp/pman'
        self._ptree             = C_snode.C_stree()

        # Comms
        self.str_protocol       = "tcp"
        self.str_IP             = "127.0.0.1"
        self.str_port           = "5010"
        self.router_raw         = 0
        self.listeners          = 1
        self.b_http             = False

        # Screen formatting
        self.LC                 = 30
        self.RC                 = 50

        for key,val in kwargs.items():
            if key == 'protocol':   self.str_protocol   = val
            if key == 'IP':         self.str_IP         = val
            if key == 'port':       self.str_port       = val
            if key == 'raw':        self.router_raw     = int(val)
            if key == 'listeners':  self.listeners      = int(val)
            if key == 'http':       self.b_http         = int(val)
            if key == 'within':     self.within         = val

        print(Colors.YELLOW)
        print("""
        \t+-----------------------------------------------+
        \t| Welcome to the pman process management system |
        \t+-----------------------------------------------+
        """)
        print(Colors.CYAN + """
        'pman' is a client/server system that allows users to monitor
        and control processes on (typically) Linux systems. Actual
        processes are spawned using the 'crunner' module and as such
        are ssh and HPC aware.

        The 'pman' server can be queried for running processes, lost/dead
        processes, exit status, etc.

        Communication from the 'pman' server is via JSON constructs.

        Typical calling syntax is:

                ./pman.py --raw 1 --http --ip <someIP> --port 5010

        Note <someIP> should be a full IP/name, and a client can interact with the
        service with a REST call, i.e.

            Using curl:

            curl -H "Content-Type: application/json"        \\
            -X POST                                         \\
            -d '{"payload": {"exec":{"cmd": "name", "args": ["arg1", "arg2", "arg3"]}, "action": "PUSH"}}' \\
            http://10.17.24.163:5010/api/login/


            Using http(ie):

            http POST http://10.17.24.163:5010/api/v1/cmd/  \\
            Content-Type:application/vnd.collection+json    \\
            Accept:application/vnd.collection+json          \\
            payload:='{"exec": {"cmd": "name", "args": ["-a", "arg1", "-b", "arg2"]}, "action": "PUSH"}'

        """)

        self.col2_print('Server is listening on',
                        '%s://%s:%s' % (self.str_protocol, self.str_IP, self.str_port))
        self.col2_print('Router raw mode',
                        str(self.router_raw))
        self.col2_print('HTTP response back mode',
                        str(self.b_http))


        # Read the DB from HDD
        self._ptree             = C_snode.C_stree()
        self.DB_read()

        # Setup zmq context
        self.zmq_context        = zmq.Context()

    def DB_read(self, **kwargs):
        """
        Read the DB from filesystem. If DB does not exist on filesystem,
        create an empty DB and save to filesystem.
        """
        if os.path.isdir(self.str_DBpath):
            self.debug("Reading pman DB from disk...\n")
            self._ptree = C_snode.C_stree.tree_load(
                pathDiskRoot    = self.str_DBpath,
                loadJSON        = True,
                loadPickle      = False)
            self.debug("pman DB read from disk...\n")
            self.col2_print('Reading pman DB from disk:', 'OK')
        else:
            P = self._ptree
            # P.cd('/')
            # P.mkdir('proc')
            P.tree_save(
                startPath       = '/',
                pathDiskRoot    = self.str_DBpath,
                failOnDirExist  = False,
                saveJSON        = True,
                savePickle      = False
            )
            self.col2_print('Reading pman DB from disk:',
                            'No DB found... creating empty default DB')
        print(Colors.NO_COLOUR, end='')

    def start(self):
        """
            Main execution.

            * Instantiate several 'listener' worker threads
                **  'listener' threads are used to process input from external
                    processes. In turn, 'listener' threads can thread out
                    'crunner' threads that actually "run" the job.
            * Instantiate a job poller thread
                **  'poller' examines the internal DB entries and regularly
                    queries the system process table, tracking if jobs
                    are still running.
        """

        self.col2_print('Starting Listener threads', self.listeners)

        # Front facing socket to accept client connections.
        socket_front = self.zmq_context.socket(zmq.ROUTER)
        socket_front.router_raw = self.router_raw
        socket_front.bind('%s://%s:%s' % (self.str_protocol,
                                          self.str_IP,
                                          self.str_port)
                          )

        # Backend socket to distribute work.
        socket_back = self.zmq_context.socket(zmq.DEALER)
        socket_back.bind('inproc://backend')

        # Start the 'listner' workers.
        for i in range(1,self.listeners+1):
            listener = Listener(    id          = i,
                                    context     = self.zmq_context,
                                    DB          = self._ptree,
                                    http        = self.b_http)
            listener.start()

        # Use built in queue device to distribute requests among workers.
        # What queue device does internally is,
        #   1. Read a client's socket ID and request.
        #   2. Send socket ID and request to a worker.
        #   3. Read a client's socket ID and result from a worker.
        #   4. Route result back to the client using socket ID.
        zmq.device(zmq.QUEUE, socket_front, socket_back)

    def __iter__(self):
        yield('Feed', dict(self._stree.snode_root))

    # @abc.abstractmethod
    # def create(self, **kwargs):
    #     """Create a new tree
    #
    #     """

    def __str__(self):
        """Print
        """
        return str(self.stree.snode_root)

    @property
    def stree(self):
        """STree Getter"""
        return self._stree

    @stree.setter
    def stree(self, value):
        """STree Getter"""
        self._stree = value

class Listener(threading.Thread):
    """ Listeners accept computation requests from front facing server.
        Parse input text streams and act accordingly. """

    def log(self, *args):
        """
        get/set the internal pipeline listener object.

        Caller can further manipulate the log object with object-specific
        calls.
        """
        if len(args):
            self._log = args[0]
        else:
            return self._log

    def name(self, *args):
        """
        get/set the descriptive name text of this object.
        """
        if len(args):
            self.__name = args[0]
        else:
            return self.__name

    def __init__(self, **kwargs):
        logging.debug('Starting __init__')
        self.debug              = message.Message(logTo = './debug.log')
        self.debug._b_syslog    = True
        self._log               = message.Message()
        self._log._b_syslog     = True
        self.__name             = "Listener"
        self.b_http             = False
        self.dp                 = debug(verbosity=0, level=-1)

        self.poller             = None

        for key,val in kwargs.items():
            if key == 'context':        self.zmq_context    = val
            if key == 'id':             self.worker_id      = val
            if key == 'DB':             self._ptree         = val
            if key == 'http':           self.b_http         = val

        threading.Thread.__init__(self)
        logging.debug('leaving __init__')

    def run(self):
        """ Main execution. """
        # Socket to communicate with front facing server.
        logging.debug('Starting run...')
        self.dp.print('starting...')
        socket = self.zmq_context.socket(zmq.DEALER)
        socket.connect('inproc://backend')

        while True:
            print(Colors.BROWN + "Listener ID - %s: run() - Ready to serve..." % self.worker_id)
            # First string received is socket ID of client
            client_id   = socket.recv()
            request     = socket.recv()
            print("\n" + Colors.BROWN + 'Listener ID - %s: run() - Received comms from client.' % (self.worker_id))
            result = self.process(request)
            # try:
            #     result = self.process(request)
            # except:
            #     print('Worker ID - %s. some error was detected' % (self.worker_id))
            #     os._exit(1)

            # For successful routing of result to correct client, the socket ID of client should be sent first.
            if result:
                print(Colors.BROWN + 'Listener ID - %s: run() - Sending response to client.' %
                      (self.worker_id))
                print('JSON formatted response:')
                str_payload = json.dumps(result)
                print(Colors.LIGHT_CYAN + str_payload)
                print(Colors.BROWN + 'len = %d chars' % len(str_payload))
                socket.send(client_id, zmq.SNDMORE)
                if self.b_http:
                    str_contentType = "application/json"
                    res  = Response(str_payload)
                    res.content_type = str_contentType

                    str_HTTPpre = "HTTP/1.x "
                    str_res     = "%s%s" % (str_HTTPpre, str(res))
                    str_res     = str_res.replace("UTF-8", "UTF-8\nAccess-Control-Allow-Origin: *")

                    socket.send(str_res.encode())
                else:
                    socket.send(str_payload)
                if result['action'] == 'quit': os._exit(1)

    def t_job_process(self, *args, **kwargs):
        """
        Main job handler -- this is in turn a thread spawned from the
        parent listener thread.

        By being threaded, the client http caller gets an immediate
        response without needing to wait on the jobs actually running
        to completion.

        """

        str_cmd         = ""

        for k,v in kwargs.items():
            if k == 'cmd':  str_cmd     = v

        self.dp.print("spawing and starting poller thread")

        # Start the 'poller' worker
        self.poller  = Poller(cmd = str_cmd)
        self.poller.start()

        str_timeStamp   = datetime.datetime.today().strftime('%Y%m%d%H%M%S.%f')
        str_uuid        = uuid.uuid4()
        str_dir         = '%s_%s' % (str_timeStamp, str_uuid)

        b_jobsAllDone   = False

        p               = self._ptree

        p.cd('/')
        p.mkcd(str_dir)

        p.mkdir('start')
        p.mkdir('end')

        jobCount        = 0
        while not b_jobsAllDone:
            try:
                b_jobsAllDone   = self.poller.queueAllDone.get_nowait()
            except queue.Empty:
                self.dp.print('Waiting on start job info')
                d_startInfo     = self.poller.queueStart.get()
                p.cd('start')
                p.mkcd('%s' % jobCount)
                p.touch('startInfo', d_startInfo.copy())
                p.cd('../../../')

                self.dp.print('Waiting on end job info')
                d_endInfo       = self.poller.queueEnd.get()
                p.cd('end')
                p.mkcd('%s' % jobCount)
                p.touch('endInfo', d_endInfo.copy())
                p.cd('../../../')
                jobCount        += 1

        p.touch('startInfo',    d_startInfo)
        p.touch('endInfo',      d_endInfo)
        p.touch('jobCount',     jobCount-1)
        p.touch('cmd',          str_cmd)

        self.dp.print('All jobs processed.')

    def json_filePart_get(self, **kwargs):
        """
        If the requested path is *within* a json "file" on the
        DB, then we need to find the file, and map the relevant
        path to components in that file.
        """

    def DB_get(self, **kwargs):
        """
        Returns part of the DB tree based on path spec in the URL
        """

        r           = C_snode.C_stree()
        p           = self._ptree

        str_URLpath = "/api/v1/"
        for k,v in kwargs.items():
            if k == 'path':     str_URLpath = v

        str_path    = '/' + '/'.join(str_URLpath.split('/')[3:])

        self.dp.print("path = %s" % str_path)

        if str_path == '/':
            # If root node, only return list of jobs
            l_rootdir = p.lstr_lsnode(str_path)
            r.mknode(l_rootdir)
        else:
            # Here is a hidden behaviour. If the 'root' dir starts
            # with an underscore, then replace that component of
            # the path with the actual name in list order.
            # This is simply a short hand way to access indexed
            # offsets.

            l_path  = str_path.split('/')
            jobID   = l_path[1]
            # Does the jobID start with an underscore?
            if jobID[0] == '_':
                jobOffset   = jobID[1:]
                l_rootdir   = list(p.lstr_lsnode('/'))
                self.dp.print('jobOffset = %s' % jobOffset)
                self.dp.print(l_rootdir)
                actualJob   = l_rootdir[int(jobOffset)]
                l_path[1]   = actualJob
                str_path    = '/'.join(l_path)

            r.mkdir(str_path)
            r.cd(str_path)
            r.cd('../')
            if not r.graft(p, str_path):
                # We are probably trying to access a file...
                # First, remove the erroneous path in the return DB
                r.rm(str_path)

                # Now, we need to find the "file", parse the json layer
                # and save...
                n                   = 0
                contents            = p.cat(str_path)
                str_pathFile        = str_path
                l_path              = str_path.split('/')
                totalPathLen        = len(l_path)
                l_pathFile          = []
                while not contents and -1*n < totalPathLen:
                    n               -= 1
                    str_pathFile    = '/'.join(str_path.split('/')[0:n])
                    contents        = p.cat(str_pathFile)
                    l_pathFile.append(l_path[n])

                if contents and n<0:
                    l_pathFile      = l_pathFile[::-1]
                    str_access      = ""
                    for l in l_pathFile:
                        b_int       = False
                        try:
                            i       = int(l)
                            b_int   = True
                        except:
                            b_int   = False
                        if b_int:
                            str_access += "[%s]" % l
                        else:
                            str_access += "['%s']" % l

                    contents        = eval('contents%s' % str_access)

                r.touch(str_path, contents)

        # print(p)
        self.dp.print(r)
        self.dp.print(dict(r.snode_root))

        return dict(r.snode_root)


    def process(self, request, **kwargs):
        """ Process the message from remote client

        In some philosophical respects, this process() method in fact implements
        REST-like API of its own.

        """

        if len(request):

            print("Listener ID - %s: process() - handling request" % (self.worker_id))

            now             = datetime.datetime.today()
            str_timeStamp   = now.strftime('%Y-%m-%d %H:%M:%S.%f')
            print(Colors.YELLOW)
            print("\n\n***********************************************")
            print("***********************************************")
            print("%s incoming data stream" % (str_timeStamp) )
            print("***********************************************")
            print("len = %d" % len(request))
            print("***********************************************")
            print(Colors.CYAN + "%s\n" % (request.decode()) + Colors.YELLOW)
            print("***********************************************" + Colors.NO_COLOUR)
            l_raw           = request.decode().split('\n')
            FORMtype        = l_raw[0].split('/')[0]

            print('Request = ...')
            print(l_raw)
            REST_header             = l_raw[0]
            REST_verb               = REST_header.split()[0]
            str_path                = REST_header.split()[1]
            json_payload            = l_raw[-1]
            str_CTL                 = ''

            d_ret                   = {}

            d_ret['status']         = False
            d_ret['RESTheader']     = REST_header
            d_ret['RESTverb']       = REST_verb
            d_ret['action']         = ""
            d_ret['path']           = str_path

            if REST_verb == 'GET':
                d_ret['GET']    = self.DB_get(path = str_path)
                d_ret['status'] = True

            if len(json_payload):
                d_payload           = json.loads(json_payload)
                d_request           = d_payload['payload']
                print("|||||||")
                print(d_request)
                print("|||||||")
                payload_verb        = d_request['action']
                d_exec              = d_request['exec']
                d_ret['payloadsize']= len(json_payload)

                # o_URL               = urlparse(str_URL)
                # str_path            = o_URL.path
                # l_path              = str_path.split('/')[2:]

                if payload_verb == 'quit':
                    print('Shutting down server...')
                    d_ret['status'] = True

                if payload_verb == 'run':
                    d_ret['cmd']    = d_exec['cmd']
                    d_ret['action'] = payload_verb
                    t_process_d_arg = {'cmd': d_exec['cmd']}

                    t_process       = threading.Thread( target  = self.t_job_process,
                                                        args    = (),
                                                        kwargs  = t_process_d_arg)
                    t_process.start()
                    d_ret['status'] = True

                    # self.job_process(cmd = d_exec['cmd'])

            return d_ret

class Poller(threading.Thread):
    """
    The Poller checks for running processes based on the internal
    DB and system process table. Jobs that are no longer running are
    removed from the internal DB.
    """
    def log(self, *args):
        """
        get/set the poller log object.

        Caller can further manipulate the log object with object-specific
        calls.
        """
        if len(args):
            self._log = args[0]
        else:
            return self._log

    def name(self, *args):
        """
        get/set the descriptive name text of this object.
        """
        if len(args):
            self.__name = args[0]
        else:
            return self.__name

    def __init__(self, **kwargs):
        self.debug              = message.Message(logTo = './debug.log')
        self.debug._b_syslog    = True
        self._log               = message.Message()
        self._log._b_syslog     = True
        self.__name             = "Poller"

        self.pollTime           = 10

        self.dp                 = debug(verbosity=0, level=-1)

        self.str_cmd            = ""
        self.crunner            = None
        self.queueStart         = queue.Queue()
        self.queueEnd           = queue.Queue()
        self.queueAllDone       = queue.Queue()

        self.dp.print('starting...', level=-1)

        for key,val in kwargs.items():
            if key == 'pollTime':       self.pollTime       = val
            if key == 'cmd':            self.str_cmd        = val

        threading.Thread.__init__(self)


    def run(self):

        timeout = 1
        loop    = 10

        """ Main execution. """

        # Spawn the crunner object container
        self.crunner  = Crunner(cmd = self.str_cmd)
        self.crunner.start()

        b_jobsAllDone   = False

        while not b_jobsAllDone:
            try:
                b_jobsAllDone = self.crunner.queueAllDone.get_nowait()
            except queue.Empty:
                # We basically propagate the queue contents "up" the chain.
                self.dp.print('Waiting on start job info')
                self.queueStart.put(self.crunner.queueStart.get())

                # print(str_jsonStart)

                self.dp.print('Waiting on end job info')
                self.queueEnd.put(self.crunner.queueEnd.get())
                # print(str_jsonEnd)

        self.queueAllDone.put(b_jobsAllDone)
        self.dp.print("done with run")

class Crunner(threading.Thread):
    """
    The wrapper thread about the actual process.
    """

    def log(self, *args):
        """
        get/set the internal crunner object.

        Caller can further manipulate the log object with object-specific
        calls.
        """
        if len(args):
            self._log = args[0]
        else:
            return self._log

    def name(self, *args):
        """
        get/set the descriptive name text of this object.
        """
        if len(args):
            self.__name = args[0]
        else:
            return self.__name

    def __init__(self, **kwargs):
        self.debug              = message.Message(logTo = './debug.log')
        self.debug._b_syslog    = True
        self._log               = message.Message()
        self._log._b_syslog     = True
        self.__name             = "Crunner"
        self.dp                 = debug(verbosity=0, level=-1)

        self.dp.print('starting crunner...', level=-1)

        self.queueStart         = queue.Queue()
        self.queueEnd           = queue.Queue()
        self.queueAllDone       = queue.Queue()

        self.str_cmd            = ""
        self.shell              = crunner.crunner(verbosity=0)

        for k,v in kwargs.items():
            if k == 'cmd':  self.str_cmd    = v

        threading.Thread.__init__(self)

    def jsonJobInfo_queuePut(self, **kwargs):
        """
        Get and return the job dictionary as a json string.
        """

        str_queue   = 'startQueue'
        for k,v in kwargs.items():
            if k == 'queue':    str_queue   = v


        if str_queue == 'startQueue':   queue   = self.queueStart
        if str_queue == 'endQueue':     queue   = self.queueEnd

        # self.dp.print(self.shell.d_job)

        queue.put(self.shell.d_job)

    def run(self):

        timeout = 1
        loop    = 10

        """ Main execution. """
        self.dp.print("running...")
        self.shell(self.str_cmd)
        # self.shell.jobs_loopctl(    onJobStart  = 'self.jsonJobInfo_queuePut(queue="startQueue")',
        #                             onJobDone   = 'self.jsonJobInfo_queuePut(queue="endQueue")')
        self.shell.jobs_loopctl(    onJobStart  = partial(self.jsonJobInfo_queuePut, queue="startQueue"),
                                    onJobDone   = partial(self.jsonJobInfo_queuePut, queue="endQueue"))
        self.queueAllDone.put(True)
        self.queueStart.put({'allJobsStarted': True})
        self.queueEnd.put({'allJobsDone': True})
        # self.shell.exitOnDone()


if __name__ == "__main__":

    parser  = argparse.ArgumentParser(description = 'simple client for talking to pman')

    parser.add_argument(
        '--ip',
        action  = 'store',
        dest    = 'ip',
        default = '127.0.0.1',
        help    = 'IP to connect.'
    )
    parser.add_argument(
        '--port',
        action  = 'store',
        dest    = 'port',
        default = '5010',
        help    = 'Port to use.'
    )
    parser.add_argument(
        '--protocol',
        action  = 'store',
        dest    = 'protocol',
        default = 'tcp',
        help    = 'Protocol to use.'
    )
    parser.add_argument(
        '--raw',
        action  = 'store',
        dest    = 'raw',
        default = '0',
        help    = 'Router raw mode.'
    )
    parser.add_argument(
        '--listeners',
        action  = 'store',
        dest    = 'listeners',
        default = '1',
        help    = 'Number of listeners.'
    )
    parser.add_argument(
        '--http',
        action  = 'store_true',
        dest    = 'http',
        default = False,
        help    = 'Send HTTP formatted replies.'
    )


    args    = parser.parse_args()

    comm    = pman(
                    IP          = args.ip,
                    port        = args.port,
                    protocol    = args.protocol,
                    raw         = args.raw,
                    listeners   = args.listeners,
                    http        = args.http
                    )
    comm.start()
