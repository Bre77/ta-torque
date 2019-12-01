from __future__ import print_function
from builtins import str
import sys
import xml.dom.minidom, xml.sax.saxutils
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import traceback
try:
    from urllib.parse import unquote
except ImportError:
    from urlparse import unquote

from pids import pids

#set up logging suitable for splunkd comsumption
logging.root
logging.root.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(levelname)s %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logging.root.addHandler(handler)

SCHEME = """<scheme>
    <title>Torque</title>
    <description>Get metrics from Torque on Android.</description>
    <use_external_validation>false</use_external_validation>
    <streaming_mode>xml</streaming_mode>

    <endpoint>
        <args>
            <arg name="email">
                <title>Email Address</title>
                <description>Enter the same email address string (doesnt need to be real) as you used in the Torque App</description>
                <data_type>string</data_type>
            </arg>

            <arg name="port">
                <title>Port</title>
                <description>The UDP port to listen on</description>
                <data_type>number</data_type>
                <validation>is_avail_udp_port('port')</validation>
            </arg>

            <arg name="bindip">
                <title>Bind IP</title>
                <description>The IP address to listen on</description>
                <required_on_create>false</required_on_create>
                <data_type>string</data_type>
            </arg>

            <arg name="multimetric">
                <title>Metric Multi-Measurement</title>
                <description>Enable the Splunk 8 Multi-Measurement mode</description>
                <required_on_create>true</required_on_create>
                <data_type>boolean</data_type>
            </arg>
        </args>
    </endpoint>
</scheme>
"""

# Empty validation routine. This routine is optional.
def validate_arguments(): 
    pass

def validate_conf(config, key):
    if key not in config:
        raise Exception("Invalid configuration received from Splunk: key '%s' is missing." % key)

# Routine to get the value of an input
def get_config():
    config = {}

    try:
        # read everything from stdin
        config_str = sys.stdin.read()

        # parse the config XML
        doc = xml.dom.minidom.parseString(config_str)
        root = doc.documentElement
        conf_node = root.getElementsByTagName("configuration")[0]
        if conf_node:
            logging.debug("XML: found configuration")
            stanza = conf_node.getElementsByTagName("stanza")[0]
            if stanza:
                stanza_name = stanza.getAttribute("name")
                if stanza_name:
                    logging.debug("XML: found stanza " + stanza_name)
                    config["name"] = stanza_name

                    params = stanza.getElementsByTagName("param")
                    for param in params:
                        param_name = param.getAttribute("name")
                        logging.debug("XML: found param '%s'" % param_name)
                        if param_name and param.firstChild and \
                           param.firstChild.nodeType == param.firstChild.TEXT_NODE:
                            data = param.firstChild.data
                            config[param_name] = data
                            logging.debug("XML: '%s' -> '%s'" % (param_name, data))

        checkpnt_node = root.getElementsByTagName("checkpoint_dir")[0]
        if checkpnt_node and checkpnt_node.firstChild and \
           checkpnt_node.firstChild.nodeType == checkpnt_node.firstChild.TEXT_NODE:
            config["checkpoint_dir"] = checkpnt_node.firstChild.data

        if not config:
            raise Exception("Invalid configuration received from Splunk.")

        # just some validation: make sure these keys are present (required)
        validate_conf(config, "port")
        validate_conf(config, "bindip")
        validate_conf(config, "multimetric")
    except Exception as e:
        raise Exception("Error getting Splunk configuration via STDIN: %s" % str(e))

    return config

# Routine to index data
def run_script(): 

    # Get Configs
    config=get_config()

    opt_multimetric=(config["multimetric"]=="True" or config["multimetric"]=="1")
    opt_ip=config["bindip"]
    opt_port=int(config["port"])
    opt_email=config.get("email",None)

    sources = {}

    class S(BaseHTTPRequestHandler):
        def _set_headers(self,code):
            self.send_response(code)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            
        def do_POST(self):
            self._set_headers(405)

        def do_HEAD(self):
            self._set_headers(200)

        def log_message(self, format, *args):
            logging.debug(' '.join(map(str,args)))

        def do_GET(self):
            try:
                if(self.path[:1] == "?"):
                    session = None
                    host = self.client_address[0]
                    data = {}
                    dims = {}
                    now = time.time()
                    query = self.path[1:].split("&")
                    for kv in query:
                        k,v = kv.split("=")
                        if k[:1] == "k":
                            ki = int(k[1:],16)
                            #do dict on id and add metric_name
                            data["metric_name:car.{}".format(pids.get(k,"pid"+hex(ki)[2:]))] = float(v)
                        elif k == "eml":
                            if opt_email and v not in opt_email.split(","):
                                logging.info(opt_email)
                                logging.info("{}!=={}".format(opt_email,v))
                                self._set_headers(400)
                                self.wfile.write("BAD EMAIL ADDRESS".encode("utf8"))
                                return
                        elif k == "time":
                            now = float(v)/1000.0 #ms to s as float
                            data["metric_name:net.latency"] = time.time()-now
                        elif k == "session": # Get Session, save as dim, and try get the related source
                            session = k
                            dims["source"] = sources.get(k,"unknown")
                        elif k == "profileName": # Set source, and if possible relate it to a session
                            dims["source"] = v
                            if session:
                                sources[session] = v
                        elif k[:13] == "userShortName": #Add missing defintions
                            ki = int(k[13:],16)
                            if ki not in pids:
                                pids[ki] = "ext.{}".format(unquote(v).replace(" ",".").replace("+","."))
                                logging.info("Adding non standard PID {} = {}".format(ki,pids[ki]))
                        elif k[:4] == "user" or k[:4] == "defa" or k[:4] == "prof": #ignore
                            pass
                        else: #dimension
                            #if opt_multimetric:
                            #    data[k] = v
                            #else:
                            dims[k] = v
                
                    #"GET ?eml=brett.whynot@gmail.com&v=8&session=1574906194609&id=0f607264fc6318a92b9e13c65db7cd3c&time=1574906292241&kff1005=153.05600033&kff1006=-27.35587294&kff1001=0.0&kff1007=0.0&kff1239=11.583717&kff1010=51.9071044921875&kff123b=0.0&kff1006=-27.35587294&kff1005=153.05600033&kff1001=0.0
                
                    if now and data:
                        if(opt_multimetric):
                            print("<stream><event><time>{}</time><host>{}</host><source>Torque</source><data>{},{}</data></event></stream>".format(now,host,json.dumps(data)[:-1],json.dumps(dims)[1:]))
                        else:
                            print("<stream>")
                            for key,value in data.items():
                                payload = dims.copy()
                                payload[key] = value
                                print("<event><time>{}</time><host>{}</host><source>Torque</source><data>{}</data></event>".format(now,host,json.dumps(payload)))
                            print("</stream>")
                        self._set_headers(200)
                        self.wfile.write("OK!".encode("utf8"))
                        return
                    else:  
                        logging.error("time={} query={}".format(now, query))
                        self._set_headers(422)
                        self.wfile.write("CANT PARSE".encode("utf8"))
                        return
                else:
                    self._set_headers(422)
                    self.wfile.write("NO DATA".encode("utf8"))
                    return

            except Exception as e:
                logging.error(e)
                logging.error(traceback.format_exc())
                self._set_headers(500)
                self.wfile.write("SCRIPT ERROR".encode("utf8"))
                return
    
    httpd = HTTPServer((opt_ip,opt_port), S)
    logging.info("Listening on {}:{} in {} metric mode".format(opt_ip,opt_port,["single","multi"][opt_multimetric]))
    httpd.serve_forever()

        

# Script must implement these args: scheme, validate-arguments
if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == "--scheme":
            print(SCHEME)
        elif sys.argv[1] == "--validate-arguments":
            validate_arguments()
        else:
            pass
    else:
        run_script()

    sys.exit(0)

