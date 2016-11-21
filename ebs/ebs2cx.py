import csv
import sys
from os import listdir, makedirs
from os.path import isfile, isdir, join, abspath, dirname, exists, basename, splitext
#==================================
# TESTING CODE - NEED TO USE
# LOCAL PACKAGE OF NETWORKN
# INSTEAD OF PIP INSTALLED VERSION
#==================================
from . import temp_append_path
sys.path.insert(1, temp_append_path)

import ndex.beta.layouts as layouts
import ndex.beta.toolbox as toolbox
from ndex.networkn import NdexGraph
from urlparse import urlsplit
import pymongo
from bson.json_util import dumps

def upload_ebs_files(dirpath, ndex, groupname=None, template_network=None, layout=None, remove_orphans=False, max=None):
    network_id_map={}
    network_map = {}
    network_count = 0
    print "max files: " + str(max)
    overlap_dict = {}
    overlap_list = []
    for filename in listdir(dirpath):
        network_count = network_count + 1
        if max is not None and network_count >= max:
            break

        print "loading ebs file #" + str(network_count) + ": " + filename
        path = join(dirpath, filename)
        network_name = basename(path)
        ebs = load_ebs_file_to_dict(path)
        ebs_network = ebs_to_network(ebs, name=network_name)

        print "layout: " + str(layout)
        if layout is not None:

            if layout == "directed_flow":
                print "applying directed_flow layout"
                layouts.apply_directed_flow_layout(ebs_network)

        print "template network: " + str(template_network)
        if isinstance(template_network, NdexGraph):
            print "applying template style"
            toolbox.apply_network_as_template(ebs_network, template_network)

        if remove_orphans:
            print "removing orphans"
            ebs_network.remove_orphans()

        print "saving network"
        #if(ebs_network.status is not None):
        #    ebs_network.status = {'status': [{"success": True, "error": ""}]}

        # Server 2 won't process aspects that are not in the metadata.
        # This is a hack to get past the template merging.
        # TODO: add metadata processing to Networkn
        #md_dict = {'nodes': 0, 'edges': 0, 'visualProperties': 0}

        network_id =ndex.save_cx_stream_as_new_network(ebs_network.to_cx_stream())

        # process nodes for enrichment
        overlap_dict[str(ebs_network)] = process_nodes_for_enrichment(ebs_network)

        network_id_map[network_name]=network_id
        version_url = network_id.rpartition('/')
        my_id = version_url[len(version_url) - 1]
        network_map[version_url] = ebs_network.nodes()

    # Process overlap
    overlap_list = process_overlap_score(overlap_dict, network_id_map)

    print 'OVERLAP: '
    print dict(data=overlap_list)

    if groupname:
        print "granting networks to group " + groupname
        ndex.grant_networks_to_group(groupname, network_id_map.values())
    return network_id_map

def process_nodes_for_enrichment(G):
    # run the nodes through the MyGene.info processor

    return set([n[1]['name'] for n in G.nodes_iter(data=True) if 'name' in n[1]])

def process_overlap_score(overlap_dict, network_id_map):
    # Process overlap
    client = pymongo.MongoClient()
    node_buckets_collection = client.cache.network_node_buckets
    network_overlap_collection = client.cache.network_overlap
    o_l = []
    for path1 in overlap_dict.keys():
        #===============================================
        # Store the network name and node list in Mongo
        #===============================================
        found_node_buckets_collection = node_buckets_collection.find_one({'net_name1': path1})
        net1_temp = network_id_map.get(path1).split('/')
        net1 = net1_temp[len(net1_temp) - 1]
        if(found_node_buckets_collection is None):
            node_buckets_collection.save({'network1': net1, 'net_name1': path1, 'node_bucket': list(overlap_dict[path1])})

        for path2 in overlap_dict.keys():
            if path1 == path2:
                next;
            else:
                overlap = overlap_dict[path1].intersection(overlap_dict[path2])
                size_overlap=len(overlap)
                if size_overlap == 0:
                    next;
                else:
                    subsumes_measure=float(size_overlap)/float(len(overlap_dict[path2]))
                    net2_temp = network_id_map.get(path2).split('/')
                    net2 = net2_temp[len(net2_temp) - 1]

                    #Check Mongo for existing record.  If one does not exist then add it
                    found_ebs_collection = network_overlap_collection.find_one({'net_name1': path1, 'net_name2': path2})
                    if(found_ebs_collection is None):
                        o_l.append({'network1': net1,'network2': net2, 'net_name1': path1, 'net_name2': path2,'overlap_size': str(size_overlap),'subsumes_measure': str(subsumes_measure), 'overlap_list':list(overlap)})
                        network_overlap_collection.save({'network1': net1,'network2': net2, 'net_name1': path1, 'net_name2': path2,'overlap_size': str(size_overlap),'subsumes_measure': str(subsumes_measure), 'overlap_list':list(overlap)})

    return o_l

def load_ebs_file_to_dict(path):
    edge_table = []
    node_table = []
    ebs = {"edge_table":edge_table, "node_table": node_table}
    network_name = path

    with open(path, 'rU') as f:
        lines = f.readlines()
        mode = "edge"
        edge_lines = []
        node_lines = []
        edge_fields = []
        node_fields = []
        for index in range(len(lines)):
            line = lines[index]
            if index is 0:
                edge_fields = [h.strip() for h in line.split('\t')]
            elif line == '\n':
                mode = "node_header"
            elif mode is "node_header":
                node_fields = [h.strip() for h in line.split('\t')]
                mode = "node"
            elif mode is "node":
                node_lines.append(line)
            elif mode is "edge":
                edge_lines.append(line)

        edge_reader = csv.DictReader(edge_lines, fieldnames=edge_fields, dialect='excel-tab')
        for dict in edge_reader:
            edge_table.append(dict)

        node_reader = csv.DictReader(node_lines, fieldnames=node_fields, dialect='excel-tab')
        for dict in node_reader:
            node_table.append(dict)

    return ebs


# Name	                            Description
# controls-state-change-of	        First protein controls a reaction that changes the state of the second protein.
# controls-transport-of	            First protein controls a reaction that changes the cellular location of the second protein.
# controls-phosphorylation-of	    First protein controls a reaction that changes the phosphorylation status of the second protein.
# controls-expression-of	        First protein controls a conversion or a template reaction that changes expression of the second protein.
# catalysis-precedes	            First protein controls a reaction whose output molecule is input to another reaction controled by the second protein.
# in-complex-with	                Proteins are members of the same complex.
# interacts-with	                Proteins are participants of the same MolecularInteraction.
# neighbor-of	                    Proteins are participants or controlers of the same interaction.
# consumption-controled-by	        The small molecule is consumed by a reaction that is controled by a protein
# controls-production-of	        The protein controls a reaction of which the small molecule is an output.
# controls-transport-of-chemical	The protein controls a reaction that changes cellular location of the small molecule.
# chemical-affects	                A small molecule has an effect on the protein state.
# reacts-with	                    Small molecules are input to a biochemical reaction.
# used-to-produce	                A reaction consumes a small molecule to produce another small molecule.
def _is_directed(rel):
    if rel in ["controls-state-change-of",
                "controls-transport-of",
                "controls-phosphorylation-of",
                "controls-expression-of",
                "catalysis-precedes",
                "controls-production-of",
                "controls-transport-of-chemical",
                "chemical-affects",
                "used-to-produce",
               ]:
        return True
    return False


def _is_filtered(rel, filter_list=["neighbor-of", "interacts-with", "controls-state-change-of"]):
    if rel in filter_list:
        return True
    return False

def _get_node_type(ebs_type):
    if ebs_type is None:
        return "Other"
    if ebs_type in ["SmallMolecule", "SmallMoleculeReference"]:
        return "SmallMolecule"
    if ebs_type in ["Complex","ComplexAssembly"]:
        return "Complex"
    if ebs_type in ["Protein","ProteinReference"]:
        return "Protein"
    if ebs_type in ["Rna","RnaReference"]:
        return "Rna"
    return "Other"

def ebs_to_network(ebs, name="not named"):
    G = NdexGraph()
    G.set_name(name)
    node_id_map = {}
    # Create Nodes
    # PARTICIPANT	PARTICIPANT_TYPE	PARTICIPANT_NAME	UNIFICATION_XREF	RELATIONSHIP_XREF
    for node in ebs.get("node_table"):
        attributes = {}
        participant = node.get("PARTICIPANT")
        participant_name = node.get("PARTICIPANT_NAME")
        if participant_name is not None:
            attributes["name"] = participant_name
        attributes["type"] = _get_node_type(node.get("PARTICIPANT_TYPE"))
        aliases = node.get("UNIFICATION_XREF")
        if aliases is not None and aliases is not "":
            attributes["aliases"] = aliases.split(",")
            #attributes["represents"] = aliases[0] - can't take first alias for ebs. Need to resolve uniprot primary id for the gene

        node_id = G.add_new_node(participant, attributes)
        node_id_map[participant] = node_id


    # Create Edges
    # PARTICIPANT_A	INTERACTION_TYPE	PARTICIPANT_B	INTERACTION_DATA_SOURCE	INTERACTION_PUBMED_ID	PATHWAY_NAMES	MEDIATOR_IDS
    for edge in ebs.get("edge_table"):
        interaction = edge.get("INTERACTION_TYPE")
        if _is_filtered(interaction):
            continue
        attributes = {}
        attributes["directed"] = _is_directed(interaction)

        pmid = edge.get("INTERACTION_PUBMED_ID")
        if pmid is not None and pmid is not "":
            attributes["pubmed"] = pmid
        source_node_id = node_id_map.get(edge.get("PARTICIPANT_A"))
        target_node_id = node_id_map.get(edge.get("PARTICIPANT_B"))
        G.add_edge_between(source_node_id, target_node_id, interaction=interaction, attr_dict=attributes)
    return G
