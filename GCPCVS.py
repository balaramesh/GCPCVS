# -*- coding: utf-8 -*-
from .BearerAuth import BearerAuth
from .getGoogleProjectNumber import getGoogleProjectNumber
import requests
import logging
import re
from time import sleep
from datetime import datetime

class GCPCVS():
    """ A class used to manage Cloud Volumes Services on GCP 
    
    All CVS objects currently handled are basically a python dict representation of
    the API JSON output. See https://cloudvolumesgcp-api.netapp.com/swagger.json
    """

    project: str = None
    projectId: str = None
    service_account: str = None
    token: BearerAuth = None
    baseurl: str = None
    headers: dict = {
                "Content-Type": "application/json",
                "User-Agent": "GCPCVS"
            }

    def __init__(self, service_account: str, project: str = None):
        """
        Args:
            service_account (str): service account key with cloudvolumes.admin permissions
                Can be specified in multiple ways:
                1. Absolute file path to an JSON key file
                2. JSON key as base64-encoded string
                3. Service Account principal name when using service account impersonation
            project (str): Google project_number or project_id or None
                If "None", project_id is fetched from service_account
                If using project_id, resourcemanager.projects.get permissions are required
        """

        self.service_account = service_account
        self.token = BearerAuth(service_account)    # Will raise ValueError is key provided is invalid

        if project == None:
            # Fetch projectID from JSON key file
            project = self.token.getProjectID()

        # Initialize projectID. Its is now either a valid projectId, or at least the project number
        self.projectId = project
        # Resolve projectID to projectNumber
        if re.match(r"[a-zA-z][a-zA-Z0-9-]+", project):
            project = getGoogleProjectNumber(project)
            if project == None:
                raise ValueError("Cannot resolve projectId to project number. Please specify project number.")
        self.project = project

        self.baseurl = 'https://cloudvolumesgcp-api.netapp.com/v2/projects/' + str(self.project)

    # print some infos on the class
    def __str__(self) -> str:
        return f"CVS: Project: {self.project}\nService Account: {self.service_account}\n"

    def getProjectNumber(self) -> int:
        return self.project
    
    def getProjectID(self) -> str:
        return self.projectId

    # Unified request response hook
    # CVS API returns error details in response body. Give users a chance to get see that messages
    def _log_response(self, resp, *args, **kwargs):
        if resp.status_code not in [200, 202]:
            logging.error(f"{resp.url} returned: {resp.text}")

   # generic GET function for internal use.
   # Adds error logging for HTTP errors and throws expections
    def _do_api_get(self, url):
        r = requests.get(url, headers=self.headers, auth=self.token, hooks={'response': self._log_response})
        r.raise_for_status()
        return r

    #
    # Volumes
    #

    def getVolumesByRegion(self, region: str) -> list[dict]:
        """ returns list with dicts of all volumes in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with volume descriptions
        """

        logging.info(f"getVolumesByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes")
        return r.json()

    def getVolumesByName(self, region: str, volname: str) -> list[dict]:
        """ returns list with dicts of volumes named "volname" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            volname (str): Name of volume

        Returns:
            list[dict]: a list of dicts with volume descriptions
        """     

        logging.info(f"getVolumesByName {region}, {volname}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes")
        return [volume for volume in r.json() if volume["name"] == volname]

    def getVolumesByVolumeID(self, region: str, volumeID: str) -> dict:
        """ returns list with dicts of volumes with "volumeID" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            volumeID (str): volumeID of volume

        Returns:
            list[dict]: a list of dicts with volume descriptions
        """     

        logging.info(f"getVolumesByVolumeID {region}, {volumeID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}")
        return r.json()
        
    def _modifyVolumeByVolumeID(self, region: str, volumeID: str, changes: dict) -> dict:
        """ Modifies a volume. Internal method
                
        Args:
            region (str): Name of GCP region
            volumeID (str): volumeID of volume
            changes (dict): dict with changes to volume

        Returns:
            dict: Returns API response as dict
        """     

        logging.info(f"modifyVolumeByVolumeID {region}, {volumeID}, {changes}")
        # read volume
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}")
        # Merge changes
        volume = {**r.json(), **changes}
        # Update volume
        r = requests.put(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}", headers=self.headers, auth=self.token, json=volume, hooks={'response': self._log_response})
        r.raise_for_status()
        return r.json()
    
    def resizeVolumeByVolumeID(self, region: str, volumeID: str, newSize: int):
        """ Resize a volume
                
        Args:
            region (str): Name of GCP region
            volumeID (str): volumeID of volume
            newSize (int): New volume size in bytes
        """  

        logging.info(f"updateVolumeByVolumeID {region}, {volumeID}, {newSize}")
        self._modifyVolumeByVolumeID(region, volumeID, {"quotaInBytes": newSize})

    def setServiceLevelByVolumeID(self, region: str, volumeID: str, serviceLevel: str):
        """ Change service level of volume
                
        Args:
            region (str): Name of GCP region
            volumeID (str): volumeID of volume
            serviceLevel (str): New service level (standard, premium, extreme) for CVS-Perf
        """  

        logging.info(f"setServiceLevelByVolumeID {region}, {volumeID}, {serviceLevel}")
        self._modifyVolumeByVolumeID(region, volumeID, {"serviceLevel": self.translateServiceLevelUI2API(serviceLevel)})

    def createVolume(self, region: str, payload: dict, timeout: int = 10) -> dict:
        """ Creates a volume. Basic method. May add more specifc ones which build on top of it later
                
        Args:
            region (str): Name of GCP region
            payload (dict): dict with all parameters
            timeout (int): Timeout in minutes, default = 10

        Returns:
            dict: Returns dict with volume description
        """

        logging.info(f"createVolume {region}, {payload}")
        retries = timeout
        while retries > 0:
            r = requests.post(f"{self.baseurl}/locations/{region}/Volumes", headers=self.headers, auth=self.token, json=payload, hooks={'response': self._log_response})
            if r.status_code == 500:
                reason = r.json()
                if 'message' in reason:                    
                    if reason['message'].startswith("Error creating volume - Cannot spawn additional jobs"):
                        logging.info(f"createVolume: Waiting for next job slot.")
                        sleep(60)
                        retries = retries - 1
                    else:
                        logging.error(f"createVolume: 500 - {reason['message']}")
                        break
                else:
                    logging.error(f"createVolume: 500 - {reason}")
                    break
            else:
                break
        r.raise_for_status()

        volumeID = r.json()['response']['AnyValue']['volumeId']
        if r.status_code == 200: 
            # volume created
            r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}")
            logging.info(f"createVolume: {region}, {volumeID} created")
            return r.json() # return data of new volume
        if r.status_code == 202: 
            # volume still creating, wait for completion
            volumeID = r.json()['response']['AnyValue']['volumeId']
            while True:
                sleep(20)
                r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}")
                state = r.json()['lifeCycleState']
                if state != "creating":
                    break
            logging.info(f"createVolume: {region}, {volumeID} created")
            return r.json() # return data of new volume. Might have failed to create. Caller needs to check lifeCycleState

        # We are not supposed to reach this code, since we either get 200 or 202 or raise an exception
        logging.error(f"createVolume: {region}, {volumeID}: reached unexpected code path")
        return {}

    def deleteVolumeByVolumeID(self, region: str, volumeID: str) -> dict:
        """ delete volumes with "volumeID" in specified region
        
        Args:
            region (str): Name of GCP region
            volumeID (str): volumeID of volume
        Returns:
            dict: Returns API response as dict            
        """     

        logging.info(f"deleteVolumeByVolumeID {region}, {volumeID}")
        retries = 10
        while retries > 0:
            r = requests.delete(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}", headers=self.headers, auth=self.token, hooks={'response': self._log_response})
            if r.status_code == 500:
                reason = r.json()
                if 'message' in reason:                    
                    if reason['message'].startswith("Error deleting volume - Cannot spawn additional jobs"):
                        logging.info(f"deleteVolumeByVolumeID: Waiting for next job slot.")
                        sleep(60)
                        retries = retries - 1
                    else:
                        logging.error(f"deleteVolumeByVolumeID: 500 - {reason['message']}")
                        break
                else:
                    break
            else:
                break
        r.raise_for_status()        
        return r.json()

    # CVS API uses serviceLevel = (basic, standard, extreme)
    # CVS UI uses serviceLevel = (standard, premium, extreme)
    # yes, the name "standard" has two different meaning *sic*
    # CVS-SO uses serviceLevel = basic, storageClass = software and regional_ha=(true|false) and
    # for simplicity reasons we translate it to serviceLevel = standard-sw
    def translateServiceLevelAPI2UI(self, serviceLevel: str) -> str:
        """ Translates service level API names to user interface names
                
        Args:
            serviceLevel (str): API service level name (basic, standard, extreme)

        Returns:
            str: UI service level name (standard, premium, extreme)
        """    

        serviceLevelsAPI = {
            "basic": "standard",
            "standard": "premium",
            "extreme": "extreme",
            "standard-sw": "standard-sw"
        }
        if serviceLevel in serviceLevelsAPI:
            return serviceLevelsAPI[serviceLevel]
        else:
            logging.warning(f"translateServiceLevelAPI2UI: Unknown serviceLevel {serviceLevel}")
            return None

    def translateServiceLevelUI2API(self, serviceLevel: str) -> str:
        """ Translates service level user interface names to API names
                
        Args:
            serviceLevel (str): UI service level name (standard, premium, extreme)

        Returns:
            str: API service level name (basic, standard, extreme)
        """    

        serviceLevelsUI = {
            "standard": "basic",
            "premium": "standard",
            "extreme": "extreme",
            "standard-sw": "standard-sw"
        }
        if serviceLevel in serviceLevelsUI:
            return serviceLevelsUI[serviceLevel]
        else:
            logging.warning(f"translateServiceLevelUI2API: Unknown serviceLevel {serviceLevel}")
            return None

    #
    # Snapshots
    #

    def getSnapshotsByRegion(self, region: str) -> list[dict]:
        """ returns list with dicts of all snapshots in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with snapshot descriptions
        """

        logging.info(f"getSnapshotsByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Snapshots")
        return r.json()

    def deleteSnapshotBySnapshotID(self, region: str, snaphotID: str) -> dict:
        """ delete snapshot with snapshotID in specified region
        
        Args:
            region (str): Name of GCP region
            snapshotID (str): snapshotID
        Returns:
            dict: Returns API response as dict            
        """     

        logging.info(f"deleteSnapshotBySnapshotID {region}, {snaphotID}")
        r = requests.delete(f"{self.baseurl}/locations/{region}/Snapshots/{snaphotID}", headers=self.headers, auth=self.token, hooks={'response': self._log_response})
        r.raise_for_status()
        return r.json()

    #
    # Replication
    #

    def getVolumeReplicationByRegion(self, region: str) -> list[dict]:
        """ returns list with dicts of all relationships in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with relationship descriptions
        """

        logging.info(f"getVolumeReplicationByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/VolumeReplications")
        return r.json()

    #
    # Backups
    #

    def getBackups(self, region: str) -> list[dict]:
        """ returns list with dicts of all backups in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with backup descriptions
        """

        logging.info(f"getBackups {region}")        
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Backups")
        return r.json()

    def getBackupsByVolumeID(self, region: str, volumeID: str) -> list[dict]:
        """ returns list with dicts of backups with "volumeID" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            volumeID (str): volumeID of volume

        Returns:
            list[dict]: a list of dicts with backup descriptions
        """  

        logging.info(f"getBackupsByVolume {region}, {volumeID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}/Backups")
        return r.json()

    # creates a CVS backup of specified volume with specified name
    def createBackup(self, region: str, volumeID: str, name: str) -> bool:
        """ Create volume backups 
        
        Args:
            region (str): Name of GCP region. "-" for all
            volumeID (str): volumeID of volume
            name (str): Name of backup

        Returns:
            bool: True if creation succeeded
        """  

        logging.info(f"createBackup {region}, {volumeID}, {name} begin")
        body = {
            "name": name,
            "volumeId": volumeID
        }
        r = requests.post(f"{self.baseurl}/locations/{region}/Backups", headers=self.headers, auth=self.token, json=body, hooks={'response': self._log_response})
        if r.status_code == 201 or r.status_code == 202:
            # Wait until backup is complete
            backupID = r.json()["response"]["AnyValue"]["backupId"]
            while True:
                sleep(5)
                r = self._do_api_get(f"{self.baseurl}/locations/{region}/Backups/{backupID}")
                status = r.json()["lifeCycleState"]
                if status == "available":
                    break
                # TODO: Implement timeout if state=available is never reached
                logging.warning(f"createBackup: Backup {name} of volume {volumeID} still in status {status}. Waiting ...")
            logging.info(f"createBackup: Backup {name} of volume {volumeID} completed.")
            return True
        else:
            logging.error(f"createBackup: Backup {name} of volume {volumeID} failed.")
            return False

    # create new backup according to name schema and delete oldest one
    def rotateBackup(self, region: str, volumeID:str , count: int) -> bool:
        logging.info(f"rotateBackup: Region: {region}, Volume: {volumeID}, Backups to keep: {count}")

        # Currently max 32 backups per volume allowed. We limit to 30 here.
        max_backups = 32

        # We will allow to do max_backups - 2 = 30 backups. We need one more, because we first create the new one before deleting old one
        if not 1 <= count <= max_backups - 2:
            logging.error(f"rotateBackup: Number of backups {count} to keep must be between 1-{max_backups - 2}.")
            return False

        # Only max_backups backups per volume allowed. Make sure we can accomodate another backup
        backups = self.getBackupsByVolumeID(region, volumeID)
        if len(backups) == max_backups:
            logging.error(f"rotateBackup: Region: {region}, Volume: {volumeID}, Cannot create new backup, since max number ({max_backups}) of backups exist.")
            return False
        logging.info(f"rotateBackup: Region: {region}, Volume: {volumeID}, Volume got {len(backups)}/{max_backups} backups")

        # Find volume name for volumeID
        vols = self.getVolumesByVolumeID(region, volumeID)
        # if len(vols) != 1:
        #     logging.error(f"rotateBackup: Region: {region}, Cannot find VolumeID: {volumeID}")
        #     return False
        volumename = vols[0]["name"]
        volumehash = volumeID[0:6]

        # Create new backup. Will fail if name already exits, e.g if ran multiple times in the same minute
        backupname = f"{volumename}-{volumehash}-{datetime.now().isoformat(timespec='minutes')}"
        if not self.createBackup(region, volumeID, backupname):
            logging.error(f"rotateBackup: Region: {region}, Volume: {volumename}, VolumeID: {volumeID}: Creating Backup {backupname} failed.")  
            return False
        # Count existing number of backups
        p = re.compile(f"{volumename}-......-\d\d\d\d-\d\d-\d\dT\d\d:\d\d")
        backups = [backup for backup in self.getBackupsByVolumeID(region, volumeID) if p.match(backup["name"])]
        # Sort by time
        sortedbackups = sorted(backups, key=lambda b: datetime.fromisoformat(b['created'].strip("Z")), reverse=True)
        # Delete 
        if len(sortedbackups) > count:
            logging.info(f"rotateBackup: Region: {region}, Volume: {volumename}, Pruning {len(sortedbackups) - count} old backup(s).")
        i = count
        while i < len(sortedbackups):
            backupToDelete = sortedbackups[i]
            self.deleteBackupbyBackupID(region, backupToDelete["backupId"])
            i = i + 1
        return True

    # Deletes a CVS backup specified by region and backupID            
    def deleteBackupByBackupID(self, region: str, backupID: str) -> bool:
        logging.info(f"deleteBackupByBackupID: {region}, {backupID} begin")
        while True:
            r = requests.delete(f"{self.baseurl}/locations/{region}/Backups/{backupID}", headers=self.headers, auth=self.token, hooks={'response': self._log_response})
            # Keep trying if 429 (Too Many Requests)
            if r.status_code != 429:
                break
            sleep(5)

        if r.status_code == 200 or r.status_code == 202:
            logging.info(f"deleteBackupByBackupID: {region}, {backupID} done.")
            return True
        else:
            logging.error(f"deleteBackupByBackupID: Deleting backup {backupID} in region {region} failed.")
            return False

    # Deletes a CVS Backup specified by region and name
    def deleteBackupByName(self, region: str, volumeID: str, name: str) -> bool:
        logging.info(f"deleteBackupByName {region}, {volumeID}, {name} begin")
        # Query all backups in region to find backupID
        backups = self.getBackupsByVolume( region, volumeID)
        backupID = [backup for backup in backups if backup["name"] == name]
        # If we found one backup with correct name, delete it
        if len(backupID) == 1:
            return self.deleteBackupbyBackupID(region, backupID[0]["backupId"])
        return False

    # deletes all backups for given volumeID. Not meant for production, but as helper for development
    # Use with care, don't go unprotected
    def deleteAllBackupsByVolumeID(self, region: str, volumeID: str):
        logging.info(f"test_deleteAllBackupsByVolumeID: Region: {region}, Volume: {volumeID}")

        for backup in self.getBackupsByVolumeID(region, volumeID):
            self.deleteBackupbyBackupID(region, backup["backupId"])            

    #
    # KMS config
    #

    def getKMSConfigurationByRegion(self, region: str) -> list[dict]:
        """ returns list with dicts of all KMS configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with KMS config descriptions
        """

        logging.info(f"getKMSConfigurationByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/KmsConfig")
        return r.json()
         
    def getKMSConfigurationByID(self, region: str, configID: str) -> list[dict]:
        """ returns list with dicts of all KMS configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all
            configID (str): UUID fo KMS configuration

        Returns:
            list[dict]: a list of dicts with KMS config descriptions
        """

        logging.info(f"getKMSConfigurationByID {region} {configID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/KmsConfig/{configID}")
        return r.json()

    def deleteKMSConfigurationByID(self, region: str, configID: str) -> bool:
        """ deletes a KMS configurations in specified region with configID
        
        Args:
            region (str): name of GCP region
            configID (str): UUID fo KMS configuration

        Returns:
            bool: True/False for success of delete operation
        """

        logging.info(f"deleteKMSConfigurationByID: {region}, {configID} begin")
        while True:
            r = requests.delete(f"{self.baseurl}/locations/{region}/Storage/KmsConfig/{configID}", headers=self.headers, auth=self.token, hooks={'response': self._log_response})
            # Keep trying if 429 (Too Many Requests)
            if r.status_code != 429:
                break
            sleep(5)

        if r.status_code == 200 or r.status_code == 202:
            logging.info(f"deleteKMSConfigurationByID: {region}, {configID} done.")
            return True
        else:
            logging.error(f"deleteKMSConfigurationByID: Deleting config {configID} in region {region} failed.")
            return False

    def getActiveDirectoryConfigurationByRegion(self, region: str) -> list[dict]:
        """ returns list with dicts of all AD configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with AD configuration descriptions
        """

        logging.info(f"getActiveDirectoryConfigurationByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/ActiveDirectory")
        return r.json()

    def getActiveDirectoryConfigurationByID(self, region: str, configID: str) -> list[dict]:
        """ returns list with dicts of all AD configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list[dict]: a list of dicts with AD configurations descriptions
        """

        logging.info(f"getActiveDirectoryConfigurationByID {region} {configID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/ActiveDirectory/{configID}")
        return r.json()

if __name__ == "__main__":
    """" Read data from CVS API
    
    Usage: GCPCVS.py <keyfile> <region> <API_path>
        credentials = File path to a valid JSON key of service account with cloudvolumes.viewer or admin permissions or SSI service account
        region = Name of GCP region or "-" for all regions
        <API_path> = Suffix part of CVS API GET call paths

    Output:
        Tool returns JSON output as returned by API. Hint: Pipe into 'jq' for further processing

    The tool automatically fetches projectID from the provided credentials.
    CVS API Paths look like:
    /v2/projects/{projectNumber}/locations/{locationId}/Volumes
    The tool automatically takes care of the 
    /v2/projects/{projectNumber}/locations/{locationId}/
    part. Just add missing part as <API_path>.
    
    Examples:
        GCPCVS.py keyfile.json - Volumes
        GCPCVS.py cvs-admin@my-project.iam.gserviceaccount.com us-east4 Volumes/704eae52-9010-ea4d-0408-08ca39ffb67f
        GCPCVS.py keyfile.json us-west1 version
        GCPCVS.py keyfile.json - Snapshots
        GCPCVS.py keyfile.json - Storage/ActiveDirectory
    """
    import sys
    import json
    from pathlib import Path

    if len(sys.argv) != 4:
        logging.notice("Usage: GCPCVS.py <credentials> <region> <API_URL_PATH>")
        sys.exit(1)

    credentials = Path(sys.argv[1])
    region = sys.argv[2]
    urlpath = sys.argv[3]

    cvs = GCPCVS(None, credentials)
    result = cvs._do_api_get(f"{cvs.baseurl}/locations/{region}/{urlpath}")
    if result.status_code == 200:
        print(json.dumps(result.json(), indent=4))
    else:
        logging.error(f"HTTP code: {result.status_code} {result.reason} for url: {result.url}")
