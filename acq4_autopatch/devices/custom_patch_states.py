# from acq4.devices.PatchPipette.states import PatchPipetteCleanState
# from acq4.devices.PatchPipette.statemanager import PatchPipetteStateManager

# implementation moved to mainline clean state
# (but leaving this here as an example of implementing custom states)

# class PatchPipetteCleanState(PatchPipetteCleanState):
#     """Customization of patch pipette cleaning state with motion control for recording chamber.
#     """
#     def run(self):
#         self.lastApproachPos = None
#         PatchPipetteCleanState.run(self)

#     def gotoApproachPosition(self, pos):
#         """
#         """
#         dev = self.dev
#         currentPos = dev.pipetteDevice.globalPosition()

#         # first move back in x and up in z, leaving y unchanged
#         print('approachHeight:', self.config['approachHeight'])
#         approachPos1 = [pos[0], currentPos[1], pos[2] + self.config['approachHeight']]
#         fut = dev.pipetteDevice._moveToGlobal(approachPos1, 'fast')
#         self.waitFor(fut)
#         if self.resetPos is None:
#             self.resetPos = approachPos1

#         # now move y over the well
#         approachPos2 = [pos[0], pos[1], pos[2] + self.config['approachHeight']]
#         fut = dev.pipetteDevice._moveToGlobal(approachPos2, 'fast')
#         self.lastApproachPos = approachPos2
#         self.waitFor(fut)


# # Install customized state class into default state list
# PatchPipetteStateManager.stateHandlers['clean'] = PatchPipetteCleanState
