from collections import OrderedDict

from . import recalibrate, test, task_runner, mock
from .patch_protocol import PatchProtocol


def all_patch_protocols(root_class=PatchProtocol):
    prots = OrderedDict()
    for cls in root_class.__subclasses__():
        if cls.name is not None:
            prots[cls.name] = cls
        prots.update(all_patch_protocols(cls))
    return prots
