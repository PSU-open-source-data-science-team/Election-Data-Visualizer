from neo4j import GraphDatabase, basic_auth, CypherError
import subprocess
import os


class Neo4jAPIException(Exception):
    '''
    Generic Exception class for the Neo4jDB API class
    '''

    def __init__(self, *args):
        if args:
            self.message = args[0]
        else:
            self.message = None

    def __str__(self):
        if self.message:
            return 'Neo4jAPIException, {0} '.format(self.message)
        else:
            return 'Neo4jAPIException has been raised.'


class Neo4jDB:
    '''
    This is the api class that contains the connector, db port info,
    login credentials, and query functions to pull information from
    the neo4j container (set up in the db_docker child class)
    '''

    def __init__(self, ip="127.0.0.1", bolt=7687, http=7474):
        # set to localhost
        self.ip = ip
        # set object to have default bolt port
        self.bolt = bolt
        # set http port
        self.http = http
        # start database driver with default password
        pw = os.environ.get("NEO4J_PASSWORD") or "test"
        print("Initializing neo4j connection driver...")
        # create db connector
        self.driver = GraphDatabase.driver(
            "bolt://%s:%d/" % (self.ip, self.bolt),
            auth=basic_auth("neo4j", pw))

    def curl_db(self, ip=None, http=None):
        '''
        Check if the neo4j db is responds
        via the selected port in the container
        :return: True if curl got an OK response, False otherwise
        '''
        # set up variables if the object has been initialized
        if ip is None:
            ip = self.ip
        if http is None:
            http = self.http
        result = subprocess.getoutput('curl -s -I  %s:%d | grep "200 OK"'
                                      % (ip, http))
        # '200 OK' in curl result indicates success
        if "200 OK" in result:
            return True
        else:
            return False

    def run_query(self, cmd):
        '''
        Execute a single Cypher query
        :param cmd: Cypher query string to execute
        :return: server response from Cypher command
        '''
        with self.driver.session() as session:
            tx = session.begin_transaction()
            try:
                ret = session.run(cmd)
                tx.commit()
                return ret
            except CypherError:
                print(f"Cypher command failed: {cmd}")
                raise Neo4jAPIException("Neo4j run_query failure.")
            except Exception as ex:
                print("Exception: ", type(ex).__name__, ex.args)
                # attempt a rollback, if possible
                try:
                    # database in possibly corrupt state, rollback
                    tx.rollback()
                except Exception:
                    # unable to rollback, just continue
                    pass
                raise Neo4jAPIException("Neo4j run_query failure.")

    def create_node(self, label, properties):
        '''
        Create node with input properties and labels
        :param label: string of ':' delimited labels
        :param properties: Cypher compliant properties
        :return: neo4j ID of the node created
        '''
        command = "CREATE (n:%s {%s}) " \
                  "RETURN ID(n)" % (label, properties)
        ret = self.run_query(command)
        try:
            # return response data
            return ret.data()[0]['ID(n)']
        except Exception:
            raise Neo4jAPIException("Neo4j create_node failure: %s" % command)

    def create_relationship_by_id(self, source_id, destination_id, rel):
        '''
        Match ID's of two different nodes, and create a new relationship
        between them
        :param source_id: ID of parent
        :param destination_id: ID of child
        :param rel: name of relationship
        :return: None
        '''
        command = 'MATCH (n) ' \
                  'WHERE ID(n) = %d ' \
                  'MATCH (m) ' \
                  'WHERE ID(m) = %d ' \
                  'MERGE (n) - [:%s] -> (m) ' \
                  'return n' % (source_id, destination_id, rel)
        self.run_query(command)

    def get_node_id_by_prop(self, prop, label=None):
        '''
        Match a name property on a node and return its ID
        :param prop: property of node
        :return: neo4j ID of matching node
        '''
        command = "MATCH (n"
        if label is not None:
            command += f":{label}"
        command += "{%s}) return ID(n)" % prop
        result = self.run_query(command)
        try:
            return result.data()[0]['ID(n)']
        except Exception:
            raise Neo4jAPIException(f"Neo4j get_node_id_by_prop failed. "
                                    f"Command: {command}")

    def create_node_with_rel_to_id(self, label, properties, relationship, id,
                                   forward=True):
        '''
        Create a new node and relationship to an existing node with matching id
        :param label: label of new node
        :param properties: properties of new node
        :param relationship: relationship label
        :param id: id of existing node to match
        :param forward: boolean directionality node from n to m
        :return: neo4j ID of node created
        '''
        # match ID
        command = "MATCH (n) " \
                  "WHERE ID(n) = %d " \
                  "CREATE (n) " % id
        # create relationship and direction
        if forward:
            command += "- [:%s] -> " % relationship
        else:
            command += "<- [:%s] - " % relationship
        # create node with label and properties
        command += "(m:%s {%s}) " \
                   "RETURN ID(m)" % (label, properties)
        result = self.run_query(command)
        try:
            return result.data()[0]['ID(m)']
        except Exception:
            raise Neo4jAPIException(f"Neo4j create_node_with_rel_to_id failed."
                                    f" Command: {command}")

    def get_node_properties_by_id(self, id):
        '''
        Get properties if the neo4j id is known
        :param id:
        :return:
        '''
        command = "MATCH (n) " \
                  "WHERE ID(n) = %d " \
                  "return n " % id
        result = self.run_query(command)
        try:
            return result.single().data()['n']
        except Exception:
            raise Neo4jAPIException(f"Neo4j get_node_properties_by_id failed."
                                    f" Command: {command}")

    def set_property_by_id(self, id, property, value):
        '''
        sets a property of node matching the neo4j id
        :param id: neo4j id of existing node to set property for
        :param property: name of property to set
        :param value: value of property to set
        :return: new nodal data
        '''
        command = f"MATCH (n) " \
                  f"WHERE ID(n) = {id} " \
                  f"SET n.{property} = {value} " \
                  f"RETURN n"
        result = self.run_query(command)
        try:
            return result.single().data()
        except Exception:
            raise Neo4jAPIException(f"Neo4j set_property_by_id failed."
                                    f" Command: {command}")

    # --- Example database specific functions below --- #
    def get_top_10_contributions(self):
        '''
        Get the top 10 contribution amounts to a Committee and display info
        about them
        :return: dict with keys name, com, pty and amt
        '''
        command = "MATCH (n:Contribution) " \
                  "match (c:Committee) " \
                  "where n.CMTE_ID = c.CMTE_ID " \
                  "with n,c " \
                  "ORDER BY n.TRANSACTION_AMT DESC " \
                  "RETURN n.NAME as name, c.CMTE_NM as com, " \
                  "c.CMTE_PTY_AFFILIATION as pty, " \
                  "MAX(n.TRANSACTION_AMT) as amt limit 10"
        result = self.run_query(command)
        try:
            return result.data()
        except Exception:
            raise Neo4jAPIException(f"Neo4j get_top_10_contributions failed."
                                    f" Command: {command}")

    def get_funded_candidates(self, pac_name):
        '''
        Find the cadidates funded by input PAC
        :return:
        '''
        command = "MATCH (:PAC {CMTE_NM:'%s'}) - [*] - (:Committee) – [*] –> "\
                  "(c:Candidate) " \
                  "return c.CAND_NAME" % pac_name
        result = self.run_query(command)
        try:
            return result.data()[0]['c.CAND_NAME']
        except Exception:
            raise Neo4jAPIException(f"Neo4j get_funded_candidates failed."
                                    f" Command: {command}")

    def get_donations_total(self, party):
        '''
        Get all the contributions for Committees with party affiliation
        :param party: party to match contributions with
        :return: integer total of contributions
        '''
        command = "MATCH (:Committee {CMTE_PTY_AFFILIATION:'%s'}) " \
                  "– [:CONTRIBUTION_TO] – (n:Contribution) " \
                  "return sum(n.TRANSACTION_AMT) as amt" % party
        result = self.run_query(command)
        try:
            return result.data()[0]['amt']
        except Exception:
            raise Neo4jAPIException(f"Neo4j get_donations_total failed."
                                    f" Command: {command}")

    def get_committee_ties(self, name):
        '''
        Get the nodes associated with a committee
        :param name: CMTE_NM of committee node
        :return: dict of nodes
        '''
        command = "match q= () - [*] - " \
                  "(:Committee {CMTE_NM:'%s'}) - [*] - () return q" % name
        result = self.run_query(command)
        try:
            return result.data()
        except Exception:
            raise Neo4jAPIException(f"Neo4j get_committee_ties failed."
                                    f" Command: {command}")
