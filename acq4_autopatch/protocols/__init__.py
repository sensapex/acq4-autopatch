from collections import OrderedDict

from . import recalibrate, test, task_runner, mock
from .patch_protocol import PatchProtocol


def allPatchProtocols(rootClass=PatchProtocol):
    prots = OrderedDict()
    for cls in rootClass.__subclasses__():
        if cls.name is not None:
            prots[cls.name] = cls
        prots.update(allPatchProtocols(cls))
    return prots
