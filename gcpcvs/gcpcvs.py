# -*- coding: utf-8 -*-
from BearerAuth import BearerAuth
from GoogleHelpers import getGoogleProjectNumber
import pandas as pd
import requests
from tabulate import tabulate
import logging
import re
import random
from time import sleep, time
from datetime import datetime, timedelta

Volume = dict
VolumeList = list[Volume]

class gcpcvs():
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
        self.token = BearerAuth(service_account)    # Will raise ValueError if key provided is invalid

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
            logging.warning(f"{resp.url} returned: {resp.text}")

   # generic GET function for internal use.
   # Adds error logging for HTTP errors and throws expections
    def _do_api_get(self, url):
        r = requests.get(url, headers=self.headers, auth=self.token, hooks={'response': self._log_response})
        r.raise_for_status()
        return r

    # generic GET function for internal use. Specify region and Suffix part of API paths to read any kind of object
    # returns request result object
    # No error handling. Handle errors yourself, using result object
    def _API_getAll(self, region, path):
        r = requests.get(f"{self.baseurl}/locations/{region}/{path}", headers=self.headers, auth=self.token, hooks={'response': self._log_response})
        r.raise_for_status()
        return r

    # generic POST function for internal use.
    # Implements waiting for job slots
    # Adds error logging for HTTP errors and throws expections
    # returns requests response object
    # use timeout_seconds == 0 for no error handling
    def _do_api_post(self, url: str, payload: dict, timeout_seconds: int = 600):
        logging.info(f"API POST {url}")

        target_time = datetime.now() + timedelta(seconds = timeout_seconds)
        while True:
            r = requests.post(url, headers=self.headers, auth=self.token, json=payload, hooks={'response': self._log_response})
            reason = r.json()

            # If timeout_seconds is 0, we are not repeat the call
            if timeout_seconds == 0:
                if r.status_code not in [200, 202]:
                    # If API call returned without 200 or 202, log error
                    logging.error(f"API POST: {reason}")
                break

            # Successful call
            if r.status_code in [200, 202]:
                break

            # For some error codes we want to sleep and repeat request
            if r.status_code in [429, 409, 500]:
                # 429 Too many requests
                # 409 Pool is already transitioning between states
                # 500 internal server error
                logging.warning(f"API POST: {reason}")
                if r.status_code == 500:
                    if 'message' in reason:
                        msg = reason['message']
                    else:
                        msg = "error"                     
                    if "Cannot spawn additional jobs" in msg:
                        pass
                    else:
                        # leave loop and let raise_for_status throw an exception
                        logging.error(f"API POST: {reason}")
                        break
                sleep(random.randrange(50,70))
            else:
                # any other HTTP error
                logging.error(f"API POST: {reason}")
                break

            # Timeout
            if datetime.now() >= target_time:
                break
        r.raise_for_status()
        return r

    # generic DELETE function for internal use.
    # Implements waiting for job slots
    # Adds error logging for HTTP errors and throws expections
    # returns requests response object
    # use timeout_seconds == 0 for no error handling
    def _do_api_delete(self, url: str, timeout_seconds: int = 120):
        logging.info(f"API DELETE {url}")

        target_time = datetime.now() + timedelta(seconds = timeout_seconds)
        while True:
            r = requests.delete(url, headers=self.headers, auth=self.token, hooks={'response': self._log_response})
            reason = r.json()

            # If timeout_seconds is 0, we are not repeat the call
            if timeout_seconds == 0:
                if r.status_code not in [200, 202]:
                    # If API call returned without 200 or 202, log error
                    logging.error(f"API POST: {reason}")
                break

            # Successful call
            if r.status_code in [200, 202]:
                break

            # For some error codes we want to sleep and repeat request
            if r.status_code in [429, 409, 500]:
                # 429 Too many requests
                # 409 Pool is already transitioning between states
                # 500 internal server error
                logging.warning(f"API POST: {reason}")
                if r.status_code == 500:
                    if 'message' in reason:
                        msg = reason['message']
                    else:
                        msg = "error"                     
                    if "Cannot spawn additional jobs" in msg:
                        pass
                    else:
                        # leave loop and let raise_for_status throw an exception
                        logging.error(f"API POST: {reason}")
                        break
                sleep(random.randrange(50,70))
            else:
                # any other HTTP error
                logging.error(f"API POST: {reason}")
                break

            # Timeout
            if datetime.now() >= target_time:
                break
        r.raise_for_status()
        return r

    def is_type_cvs(self, region: str) -> bool:
        """ returns True if CVS-SW is available in specified region
        
        Args:
            region (str): Name of GCP region

        Returns:
            bool: True is service type is available in the specified region
        """           
        available_sw_regions = ['asia-east2', 'asia-northeast2', 'asia-northeast3', 'asia-south1', 'asia-south2', 'asia-southeast2',
                             'australia-southeast2',
                             'europe-central2', 'europe-north1', 'europe-west1', 'europe-west6',
                             'southamerica-east1',
                             'us-east1', 'us-west1']
        return region in available_sw_regions
        
    def is_type_cvs_performance(self, region: str) -> bool:
        """ returns True if CVS-Performance is available in specified region
        
        Args:
            region (str): Name of GCP region

        Returns:
            bool: True is service type is available in the specified region
        """           
        available_hw_regions = ['asia-northeast1', 'asia-southeast1',
                             'australia-southeast1',
                             'europe-west2', 'europe-west3', 'europe-west4', 'europe-southwest1',
                             'northamerica-northeast1', 'northamerica-northeast2',
                             'us-central1', 'us-east4', 'us-west2', 'us-west3', 'us-west4']
        return region in available_hw_regions

    def getVersionByRegion(self, region: str) -> dict:
        """ returns API and SDE version for specified region
        
        Also checks for API permissions
        
        Args:
            region (str): name of GCP region
        """
        res = self._do_api_get(f"{self.baseurl}/locations/{region}/version")
        return res.json()

    #
    # StoragePools
    #

    def getPoolsByRegion(self, region: str) -> list:
        """ returns list with dicts of all pools in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with pool descriptions
        """

        logging.info(f"getPoolsByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Pools")
        return r.json()

    def getPoolsByName(self, region: str, name: str) -> list:
        """ returns list with dicts of pools named "name" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            name (str): Name of pool

        Returns:
            list: a list of dicts with pool descriptions
        """     

        logging.info(f"getPoolsByName {region}, {name}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Pools")
        return [pool for pool in r.json() if pool["name"] == name]

    def getPoolsByPoolID(self, region: str, poolID: str) -> dict:
        """ returns list with dicts of volumes with "poolID" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            poolID (str): poolID of pool

        Returns:
            list: a list of dicts with pool descriptions
        """     

        logging.info(f"getPoolByPoolID {region}, {poolID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Pools/{poolID}")
        return r.json()

    def createPool(self, region: str, payload: dict, timeout: int = 15*60) -> dict:
        """ Creates a StoragePool. Basic method. May add more specifc ones which build on top of it later
                
        Args:
            region (str): Name of GCP region
            payload (dict): dict with all parameters
            timeout (int): timeout in seconds, default = 15*60

        Returns:
            dict: Returns dict with pool description
        """

        logging.info(f"createPool {region}, {payload}")
        r = self._do_api_post(f"{self.baseurl}/locations/{region}/Pools", payload, timeout)

        poolID = r.json()['response']['AnyValue']['poolId']
        if r.status_code == 200: 
            # pool created
            r = self._do_api_get(f"{self.baseurl}/locations/{region}/Pools/{poolID}")
            logging.info(f"createVolume: {region}, {poolID} created")
            return r.json() # return data of new volume
        if r.status_code == 202: 
            # pool still creating, wait for completion
            volumeID = r.json()['response']['AnyValue']['poolId']
            while True:
                sleep(20)
                r = self._do_api_get(f"{self.baseurl}/locations/{region}/Pools/{poolID}")
                state = r.json()['state']
                if state != "creating":
                    break
            logging.info(f"createPool: {region}, {poolID} created")
            return r.json() # return data of new pool. Might have failed to create. Caller needs to check lifeCycleState

        # We are not supposed to reach this code, since we either get 200 or 202 or raise an exception
        logging.error(f"createPool: {region}, {poolID}: reached unexpected code path")
        return {}

    def _modifyPoolByPoolID(self, region: str, poolID: str, changes: dict) -> dict:
        """ Modifies a pool. Internal method
                
        Args:
            region (str): Name of GCP region
            volumeID (str): poolID of volume
            changes (dict): dict with changes to pool

        Returns:
            dict: Returns API response as dict
        """     

        logging.info(f"_modifyPoolByPoolID {region}, {poolID}, {changes}")
        # Update pool
        r = requests.put(f"{self.baseurl}/locations/{region}/Pools/{poolID}", headers=self.headers, auth=self.token, json=changes, hooks={'response': self._log_response})
        r.raise_for_status()
        # Add code to wait for completion?
        return r.json()
    
    def resizePoolByPoolID(self, region: str, poolID: str, newSize: int) -> dict:
        """ Resize a pool
                
        Args:
            region (str): Name of GCP region
            poolID (str): poolID of pool
            newSize (int): New pool size in bytes

        Returns:
            dict: Returns API response as dict
        """  

        logging.info(f"resizePoolByPoolID {region}, {poolID}, {newSize}")
        return self._modifyPoolByPoolID(region, poolID, {"sizeInBytes": newSize})

    def deletePoolByPoolID(self, region: str, poolID: str) -> dict:
        """ delete poolID with "poolID" in specified region
        
        Args:
            region (str): Name of GCP region
            poolID (str): poolID of pool
        Returns:
            dict: Returns API response as dict            
        """     

        logging.info(f"deletePoolByPoolID {region}, {poolID}")
        r = self._do_api_delete(f"{self.baseurl}/locations/{region}/Pools/{poolID}", 10*60)
        # Add code to wait for completion?
        return r.json()

    #
    # Volumes
    #

    def getVolumesByRegion(self, region: str) -> list:
        """ returns list with dicts of all volumes in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with volume descriptions
        """

        logging.info(f"getVolumesByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes")
        return r.json()

    def getVolumesByName(self, region: str, name: str) -> list:
        """ returns list with dicts of volumes named "name" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            name (str): Name of volume

        Returns:
            list: a list of dicts with volume descriptions
        """     

        logging.info(f"getVolumesByName {region}, {name}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Volumes")
        vols = [volume for volume in r.json() if volume["name"] == name]
        # Do a lookup of volumeId, since to generic query returns less details compared to volumeID query
        # We actuall expect only one or no volule to match the name
        if len(vols) == 1:
            return [self.getVolumesByVolumeID(region, vols[0]['volumeId'])]
        else:
            return []

    def getVolumesByVolumeID(self, region: str, volumeID: str) -> dict:
        """ returns list with dicts of volumes with "volumeID" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            volumeID (str): volumeID of volume

        Returns:
            list: a list of dicts with volume descriptions
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

        logging.info(f"_modifyVolumeByVolumeID {region}, {volumeID}, {changes}")
        # Update volume
        r = requests.put(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}", headers=self.headers, auth=self.token, json=changes, hooks={'response': self._log_response})
        r.raise_for_status()
        return r.json()
    
    def resizeVolumeByVolumeID(self, region: str, volumeID: str, newSize: int) -> dict:
        """ Resize a volume
                
        Args:
            region (str): Name of GCP region
            volumeID (str): volumeID of volume
            newSize (int): New volume size in bytes

        Returns:
            dict: Returns API response as dict
        """  

        logging.info(f"updateVolumeByVolumeID {region}, {volumeID}, {newSize}")
        return self._modifyVolumeByVolumeID(region, volumeID, {"quotaInBytes": newSize})

    def setServiceLevelByVolumeID(self, region: str, volumeID: str, serviceLevel: str):
        """ Change service level of volume
                
        Args:
            region (str): Name of GCP region
            volumeID (str): volumeID of volume
            serviceLevel (str): New service level (standard, premium, extreme) for CVS-Perf
        """  

        logging.info(f"setServiceLevelByVolumeID {region}, {volumeID}, {serviceLevel}")
        self._modifyVolumeByVolumeID(region, volumeID, {"serviceLevel": self.translateServiceLevelUI2API(serviceLevel)})

    def createVolume(self, region: str, payload: dict, timeout: int = 15*60) -> dict:
        """ Creates a volume. Basic method. May add more specific ones which build on top of it later
                
        Args:
            region (str): Name of GCP region
            payload (dict): dict with all parameters
            timeout (int): timeout in seconds, default = 15*60

        Returns:
            dict: Returns dict with volume description
        """

        logging.info(f"createVolume {region}, {payload}")
        if 'isDataProtection' in payload and payload['isDataProtection'] == True:
            # Create a Data Protection volume
            r = self._do_api_post(f"{self.baseurl}/locations/{region}/DataProtectionVolumes", payload, timeout)
        else:
            r = self._do_api_post(f"{self.baseurl}/locations/{region}/Volumes", payload, timeout)

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
        r = self._do_api_delete(f"{self.baseurl}/locations/{region}/Volumes/{volumeID}", 10*60)
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

    def getSnapshotsByRegion(self, region: str) -> list:
        """ returns list with dicts of all snapshots in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with snapshot descriptions
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
        r = self._do_api_delete(f"{self.baseurl}/locations/{region}/Snapshots/{snaphotID}", 2*60)
        return r.json()

    #
    # Replication
    #

    def getVolumeReplicationByRegion(self, region: str) -> list:
        """ returns list with dicts of all relationships in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with relationship descriptions
        """

        logging.info(f"getVolumeReplicationByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/VolumeReplications")
        return r.json()

    def getVolumeReplicationByID(self, region: str, relationshipID: str) -> list:
        """ returns list with dicts of all relationships in specified region with relationshipID (one expected)
        
        Args:
            region (str): name of GCP region. 
            relationshipID (str): ID of relationship

        Returns:
            list: a list of dicts with relationship descriptions
        """

        logging.info(f"getVolumeReplicationByID {region} {relationshipID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/VolumeReplications/{relationshipID}")
        return r.json()    

    def getVolumeReplicationByName(self, region: str, name: str) -> list:
        """ returns list with dicts of all relationships in specified region with name (one expected)

        Args:
            region (str): name of GCP region
            name (str): name of relationship

        Returns:
            list: a list of dicts with relationship descriptions
        """

        logging.info(f"getVolumeReplicationByName {region} {name}")
        relationships = self.getVolumeReplicationByRegion(region)
        return [r for r in relationships if r['name'] == name]

    def createVolumeReplication(self, relationship_name: str, source_volume: Volume, destination_volume: Volume, schedule: str) -> dict:
        """ Creates a Volume Replication Relationship.
                
        Args:
            relationship_name (str): Name of the Volume Replication relationship
            source_volume (dict): dictionary of source volume
            destination_volume (dict): dictionary of destination volume
            schedule (str): Replication schedule (10minutely|hourly|daily)

        Returns:
            dict: Returns dict with replication description
        """

        logging.info(f"createVolumeReplication {relationship_name}")
        region = destination_volume["region"]
        # Add check if destination is Secondary and available
        if destination_volume['isDataProtection'] == False:
            # destination volume needs to be a secondary volume
            raise ValueError(f"Volume {destination_volume['volumeId']} needs to by a secondary/dataprotection volume.")
        if destination_volume['inReplication'] == True:
            # destination already in a replicationship. May add code later to read the relationship and return its data instead of none
            logging.warning(f"createVolumeReplication {relationship_name}: Destination volume {destination_volume['volumeId']} already in replication state.")
            return None
        # Check if schedule is valid string
        if schedule not in ['10minutely', 'hourly', 'daily']:
            raise ValueError(f"Invalid schedule: {schedule} (10minutely|hourly|daily)")

        payload = {
            "destinationVolumeUUID": destination_volume["volumeId"],
            "endpointType": "dst",
            "name": relationship_name,
            "remoteRegion": source_volume["region"],
            "replicationPolicy": "MirrorAllSnapshots",
            "replicationSchedule": schedule,
            "sourceVolumeUUID": source_volume["volumeId"]
        }
        print(f"{self.baseurl}/locations/{region}/VolumeReplications")
        logging.info(f"createVolumeReplication {relationship_name} {payload}")
        r = self._do_api_post(f"{self.baseurl}/locations/{region}/VolumeReplications", payload)
        # TODO: Should we wait until it is available in mirrored state? And return a full CRR json?
        return r

    def breakVolumeReplicationByID(self, destination_region: str, relationshipID: str, force: bool) -> dict:
        """ breaks a replication relationship with "relationshipID" in specified region
        
        Args:
            destination_region (str): Name of GCP region of destination volume
            relationshipID (str): ID of replication relationship
            force (bool): Force break True/False
        Returns:
            dict: Returns API response as dict            
        """     

        logging.info(f"breakVolumeReplicationByID {destination_region}, {relationshipID}, {force}")
        payload = {
            "force": force
        }
        r = self._do_api_post(f"{self.baseurl}/locations/{destination_region}/VolumeReplications/{relationshipID}/Break", payload)

        # Wait for connection to be broken
        start = time()
        while True:
            sleep(15)
            res = self._do_api_get(f"{self.baseurl}/locations/{destination_region}/VolumeReplications/{relationshipID}")
            if res.json()['lifeCycleState'] == 'available':
                break
            if res.json()['lifeCycleState'] == 'error':
                logging.error(f"breakVolumeReplicationByID {destination_region}, {relationshipID}: {res.json()['lifeCycleStateDetails']}")
                raise RuntimeError(res.json()['lifeCycleStateDetails'])
            # Add timeout in case relationship never becomes available
            if time() > start + 5*60:
                raise TimeoutError(f"breakVolumeReplicationByID {destination_region}, {relationshipID} Waiting for break to finish timed out")
            logging.info(f"breakVolumeReplicationByID {destination_region}, {relationshipID} Waiting for break to complete")
        return res.json()

    def resyncVolumeReplicationByID(self, destination_region: str, relationshipID: str) -> dict:
        """ resyncs a replication relationship with "relationshipID" in specified region

        Args:
            destination_region (str): Name of GCP region of destination volume
            relationshipID (str): ID of replication relationship
        Returns:
            dict: Returns API response as dict
        """

        logging.info(f"resyncVolumeReplicationByID {destination_region}, {relationshipID}")
        payload = {
        }
        r = self._do_api_post(f"{self.baseurl}/locations/{destination_region}/VolumeReplications/{relationshipID}/Resync", payload)
        # TODO: Should we wait until it is available in mirrored state? And return a full CRR json?
        return r.json()

    def createReverseVolumeReplicationByID(self, relationship_region: str, relationshipID: str) -> dict:
        """ reverse resyncs a replication relationship with "relationshipID" in specified region

        Args:
            relationship_region (str): Region where existing CRR relationship is managed
            relationshipID (str): ID of replication relationship
        Returns:
            dict: Returns API response as dict

        It creates a new relationship with directions reversed. Take the same relatonship name and
        attached "-reversed" to it
        """

        logging.info(f"createReverseVolumeReplicationByID {relationship_region}, {relationshipID}")
        # read existing relationship
        relationship = self.getVolumeReplicationByID(relationship_region, relationshipID)

        # is relationship broken?
        if relationship['mirrorState'] != 'broken':
            logging.error(f"createReverseVolumeReplicationByID {relationship_region}, {relationshipID} - mirror not broken")
            raise ValueError(f"createReverseVolumeReplicationByID {relationship_region}, {relationshipID} - mirror not broken")
        if relationship['relationshipStatus'] != 'idle':
            logging.error(f"createReverseVolumeReplicationByID {relationship_region}, {relationshipID} - relationshipStatus not idle")
            raise ValueError(f"createReverseVolumeReplicationByID {relationship_region}, {relationshipID} - relationshipStatus not idle")
        # Maybe check volumes for isInReplication? How do we know this is a valid resync? It builds a new connection

        payload = {
            "destinationVolumeUUID": relationship['sourceVolumeUUID'],
            "sourceVolumeUUID": relationship['destinationVolumeUUID'],
            "remoteRegion": relationship['destinationRegion'],
            "endpointType": "dst",
            "name": relationship['name'] + "-reversed",
            "replicationPolicy": relationship['replicationPolicy'],
            "replicationSchedule": relationship['replicationSchedule'],
        }
        reverse_relationship = self._do_api_post(f"{self.baseurl}/locations/{relationship['remoteRegion']}/VolumeReplications", payload)

        # TODO: Should we wait until it is available in mirrored state? And return a full CRR json?
        return reverse_relationship.json()

    def deleteVolumeReplicationByID(self, region: str, relationshipID: str) -> dict:
        """ delete replication relationship with "relationshipID" in specified region
        
        Args:
            region (str): Name of GCP region
            relationshipID (str): ID of replication relationship
        Returns:
            dict: Returns API response as dict            
        """     

        logging.info(f"deleteVolumeReplicationByID {region}, {relationshipID}")
        r = self._do_api_delete(f"{self.baseurl}/locations/{region}/VolumeReplications/{relationshipID}", 10*60)
        # TODO: Should we wait until the delete is complete?
        return r.json()

    #
    # Backups
    #

    def getBackups(self, region: str) -> list:
        """ returns list with dicts of all backups in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with backup descriptions
        """

        logging.info(f"getBackups {region}")        
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Backups")
        return r.json()

    def getBackupsByVolumeID(self, region: str, volumeID: str) -> list:
        """ returns list with dicts of backups with "volumeID" in specified region
        
        Args:
            region (str): Name of GCP region. "-" for all
            volumeID (str): volumeID of volume

        Returns:
            list: a list of dicts with backup descriptions
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
        r = self._do_api_post(f"{self.baseurl}/locations/{region}/Backups", body, 10*60)
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

        r = self._do_api_delete(f"{self.baseurl}/locations/{region}/Backups/{backupID}", 10*60)
        if r.status_code in [200, 202]:
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

    def getKMSConfigurationByRegion(self, region: str) -> list:
        """ returns list with dicts of all KMS configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with KMS config descriptions
        """

        logging.info(f"getKMSConfigurationByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/KmsConfig")
        return r.json()
         
    def getKMSConfigurationByID(self, region: str, configID: str) -> list:
        """ returns list with dicts of all KMS configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all
            configID (str): UUID fo KMS configuration

        Returns:
            list: a list of dicts with KMS config descriptions
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
        r = self._do_api_delete(f"{self.baseurl}/locations/{region}/Storage/KmsConfig/{configID}", 2*60)
        if r.status_code in [200, 202]:
            logging.info(f"deleteKMSConfigurationByID: {region}, {configID} done.")
            return True
        else:
            logging.error(f"deleteKMSConfigurationByID: Deleting config {configID} in region {region} failed.")
            return False

    #
    # Active Directory config
    #

    def getActiveDirectoryConfigurationByRegion(self, region: str) -> list:
        """ returns list with dicts of all AD configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with AD configuration descriptions
        """

        logging.info(f"getActiveDirectoryConfigurationByRegion {region}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/ActiveDirectory")
        return r.json()

    def getActiveDirectoryConfigurationByID(self, region: str, configID: str) -> list:
        """ returns list with dicts of all AD configurations in specified region
        
        Args:
            region (str): name of GCP region. "-" for all

        Returns:
            list: a list of dicts with AD configurations descriptions
        """

        logging.info(f"getActiveDirectoryConfigurationByID {region} {configID}")
        r = self._do_api_get(f"{self.baseurl}/locations/{region}/Storage/ActiveDirectory/{configID}")
        return r.json()

if __name__ == "__main__":
    """" Read data from CVS API
    
    Usage: gcpcvs.py <keyfile> <region> <API_path>
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
        gcpcvs.py keyfile.json - Volumes
        gcpcvs.py cvs-admin@my-project.iam.gserviceaccount.com us-east4 Volumes/704eae52-9010-ea4d-0408-08ca39ffb67f
        gcpcvs.py keyfile.json us-west1 version
        gcpcvs.py keyfile.json - Snapshots
        gcpcvs.py keyfile.json - Storage/ActiveDirectory
    """
    import sys
    import json
    from pathlib import Path

    if len(sys.argv) != 4:
        logging.warning("Usage: gcpcvs.py <credentials> <region> <API_URL_PATH>")
        sys.exit(1)

    credentials = Path(sys.argv[1])
    region = sys.argv[2]
    urlpath = sys.argv[3]

    cvs = gcpcvs(credentials)
    result = cvs._do_api_get(f"{cvs.baseurl}/locations/{region}/{urlpath}")
    if result.status_code == 200:
#        for  result.json()).items():
#             print (
#        print(json.dumps(result.json(), indent=4))
        json_object = json.loads(json.dumps(result.json()))
#        print("This is the type of object that summarizes all available volumes")
#        print(type(json_object))
        for iterator in json_object:
            volume_id = iterator['volumeId']
            volume_result = cvs._do_api_get(f"{cvs.baseurl}/locations/{region}/{urlpath}/{volume_id}")
            if volume_result.status_code == 200:
               volume_json_object = json.loads(json.dumps(volume_result.json()))
 #              print("This is the type of Volume JSON Object")
 #              print(type(volume_json_object))
               export_policy = volume_json_object['exportPolicy']
 #              print("This is type of export policy")
 #              print(type(export_policy))
 #              print("Type of export policy rules")
 #              print(type(export_policy['rules']))
 #              print(export_policy['rules'])
               for i in export_policy['rules']:
                   i['hasRootAccess'] = "false"
 #                  print("Updated value of export policy rule")
 #                  print(i)
 #              print("This is my export policy now")
 #              print(export_policy)
               print("Execute Volume Update for volume: " + iterator['name'])
               print(json.dumps(cvs._modifyVolumeByVolumeID(region, volume_id, {"exportPolicy": export_policy}), indent=4))
#       df = pd.DataFrame.from_dict(r)
#       print("Tabulated output:\n")
#       print(tabulate(df), headers=['name','exportPolicy.rules.)
#    else:
#        logging.error(f"HTTP code: {result.status_code} {result.reason} for url: {result.url}")


#    print("Output:\n")
#    print(json.dumps(cvs._modifyVolumeByVolumeID(region, "26336752-75df-4f80-592b-9ac7a9f4352a",{"exportPolicy":{"rules":[{"access":"ReadWrite","allowedClients":"0.0.0.0/0","hasRootAccess":"off","kerberos5ReadOnly":{"checked":False},"kerberos5ReadWrite":{"checked":False},"kerberos5iReadOnly":{"checked":False},"kerberos5iReadWrite":{"checked":False},"kerberos5pReadOnly":{"checked":False},"kerberos5pReadWrite":{"checked":False},"nfsv3":{"checked":True},"nfsv4":{"checked":True}}]}}), indent=4))
#    result = cvs._do_api_get(f"{cvs.baseurl}/locations/{region}/{urlpath}")
#    if result.status_code == 200:
#       print(json.dumps(result.json(), indent=4))
#       df = pd.DataFrame.from_dict(r)
#       print("Tabulated output:\n")
#       print(tabulate(df), headers=['name','exportPolicy.rules.)
    else:
       logging.error(f"HTTP code: {result.status_code} {result.reason} for url: {result.url}")
