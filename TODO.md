# Elements to be developed:

## OSC:
 - Define node-specific status endpoints for OSC
 - Add a new tool for the server to check the status of the OSC
 - Register controller endpoints for OSC on NodeEngine
 - Properly split between OssiaClient and PlayerClient to remove set_values calls from OSCQueryDevice instances

## Editor-Controller communications:
 - Unify return_message structure between editor and controller:
    - Is `action_uuid` required? Should not be replaced by `context`?
    - `type` and `action` should be equivalent?
    - will `value` always be `'OK'` for `confirm_to_editor`?
