import time


class PatchProtocol(object):
    """Base class for defining actions to perform once a cell+pipette have been selected and are
    ready for patching.

    This class may be customized to provide support for new experiment types.

    Might include actions like:
    - Move pipette to cell
    - Take brightfield image
    - Attempt patch
    - Initiate reocrding protocol
    - Various abort procedures
    - Clean / swap pipette
    """

    name = None

    def __init__(self, patchThread, patchAttempt):
        self.patchThread = patchThread
        self.patchAttempt = patchAttempt

    def runPatchProtocol(self):
        """Implements (in subclass) the sequence of actions defining this protocol.

        This method should call self.checkStop() periodically in order to respond
        to abort requests.
        """
        raise NotImplementedError()

    def abortPatchProtocol(self):
        """This method is called when the protocol has stopped early; may be reimplemented
        to perform cleanup.
        """
        raise NotImplementedError()

    def checkStop(self):
        """Raise an exception if an abort was requested.
        """
        self.patchThread.checkStop()

    def lock(self, lock, timeout=20.0):
        """Return a context manager that attempts to lock a mutex while checking for abort requests.
        """
        return Locker(self, lock, timeout)

    def wait(self, futures, timeout=20.0):
        """Wait for multiple futures to complete while also checking for abort requests.
        """
        if len(futures) == 0:
            return
        start = time.time()
        while True:
            self.checkStop()
            allDone = True
            for fut in futures[:]:
                try:
                    fut.wait(0.2)
                    futures.remove(fut)
                except fut.Timeout:
                    allDone = False
                    break
            if allDone:
                break
            if timeout is not None and time.time() - start > timeout:
                raise futures[0].Timeout(f"Timed out waiting for {futures!r}")


class Locker(object):
    """Mutex locker that periodically checks for protocol abort requests.
    """

    class Timeout(Exception):
        pass

    def __init__(self, protocol, lock, timeout=20.0):
        self.protocol = protocol
        self.lock = lock
        self.timeout = timeout
        self.unlock = False

    def __enter__(self):
        start = time.time()
        while True:
            if self.lock.tryLock(200):
                self.unlock = True
                self.protocol.checkStop()
                return self
            if self.timeout is not None and time.time() - start > self.timeout:
                raise Locker.Timeout("Timed out waiting for lock")

    def __exit__(self, *args):
        if self.unlock:
            self.lock.unlock()
