"""
Integration with legacy filesystem.

The goal of this module is to make sure that the NG submission system can put
files in the right place on the legacy filesystem when a submission is
finalized. Until moderation and publication are decoupled from the SFS
filesystem, we need to ensure that submission content ends up in expected
places for those components to continue to function correctly.

.. note::

   NG components MUST NOT use this module to access submission content! Access
   is provided by the file management service, via its API.

"""
from .store import store_source, get_source, ConfigurationError, SecurityError