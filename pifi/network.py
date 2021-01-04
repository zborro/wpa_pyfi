#!/usr/bin/python3
#
# @file    network.py
# 
# @brief       
#
# @author  Garrett Hagen <garretthagen21@gmail.com>
# 
# @date    2021-01-03 
#



import subprocess
from ifconfigparser import IfconfigParser


class Network(object):
    """Represents a single network block in wpa_supplicant.conf."""

    WPA_SUPPLICANT_CONFIG = "/etc/wpa_supplicant/wpa_supplicant.conf"
    DEFAULT_INTERFACE = 'wlan0'

    @classmethod
    def for_file(cls, wpa_supplicant_config):
        """
        A class factory for providing a nice way to specify the interfaces file
        that you want to use.  Use this instead of directly overwriting the
        interfaces Class attribute if you care about thread safety.
        """
        return type(cls)(cls.__name__, (cls,), {
            'WPA_SUPPLICANT_CONFIG': wpa_supplicant_config,
        })

    def __init__(self, ssid, **opts):
        self.ssid = ssid
        self.opts = opts
        self.interface = Network.DEFAULT_INTERFACE

    def __repr__(self):
        string = 'network={\n'
        string += '\tssid="{}"\n'.format(self.ssid)
        for opt, val in self.opts.items():
            string += '\t{}={}\n'.format(opt, val)
        string += '}'
        return string

    @property
    def nickname(self):
        return self.opts.get("id_str")

    def set_interface(self, interface):
        self.interface = interface

    def save(self, overwrite=True, supplicant_file=WPA_SUPPLICANT_CONFIG):
        u"""Write to the appropriate config file.
        Will refuse to overwrite an already present file unless explicitly told
        to do so via the 'overwrite' parameter.
        Arguments:
            overwrite -- ignore any existing files. Defaults to False.
            supplicant_file -- the file in which the config will be written.
                Defaults to WPA_SUPPLICANT_CONFIG (global setting).

        """
        # Handle any existing networks
        existing_network = Network.find(self.ssid)
        if existing_network:
            if not overwrite:
                print("Network: " + str(
                    self) + " already exists in " + supplicant_file + " and overwrite is False. Ignoring save")
                return
            else:
                existing_network.delete()

        # Save the file
        with open(supplicant_file, 'a') as wpa_config:
            wpa_config.write('\n')
            # wpa_config.write('\n# This Network Entry was Automatically Created by wpa-pifi Python Module #\n')
            wpa_config.write(str(self))
            wpa_config.write('\n')

    def delete(self, supplicant_file=WPA_SUPPLICANT_CONFIG):
        """
        Deletes the configuration from the :attr:`interfaces` file.
        """

        # Read in the contents of supplicant conf
        file_in = open(supplicant_file, 'r')
        all_lines = file_in.readlines()
        file_in.close()

        curr_index = 0
        entry_start_index = None
        entry_end_index = None
        entry_found = False

        # Iterate through the files to see what we will keep
        for line in all_lines:
            line = line.strip()

            # If line exists and is not whitespace or comment we will analyze it
            if line and not line.startswith("#"):

                # We are at the beginning of an entry block and have not found our entry yet
                if "network" and "{" in line and not entry_found:
                    entry_start_index = curr_index

                # The current line contains the ssid or nick name we are looking for and we are in a block
                elif ("ssid" and self.ssid in line) or \
                        (self.nickname and ("id_str" and self.nickname in line)) \
                        and entry_start_index:
                    entry_found = True

                # We have reached end bracket, have found our entry, and have not yet set the end block
                elif "}" in line and entry_found and not entry_end_index:
                    entry_end_index = curr_index

            curr_index += 1

        # If we have valid indices and an entry has been found, remove everything between the two indicies
        if entry_found and entry_start_index and entry_end_index:
            # End index is calculated inclusively, but sliced exclusively so add 1
            entry_end_index = min(entry_end_index + 1, len(all_lines))

            # Remove the entry from all lines
            all_lines = all_lines[:entry_start_index] + all_lines[entry_end_index:]

            # Piece the list back together
            wpa_supplicant_temp_file = supplicant_file + ".tmp"
            file_output = ''.join(all_lines)
            temp_file = open(wpa_supplicant_temp_file, 'w')
            temp_file.write(file_output)
            temp_file.close()

            # Overwrite the actual file with the temp file
            subprocess.check_output(['mv', wpa_supplicant_temp_file, supplicant_file])

            # Reload wpa client in case we deleted the network we were connected to
            self._reload_wpa_client()

            return True
        else:
            print("Could Not Find Entry for Network: " + self.ssid + " in " + supplicant_file)
            return False

    def add_option(self, option_key, option_value):
        self.opts[option_key] = option_value

    def activate(self, save_first=True):
        """
        Connects to the network as configured in this scheme.
        """
        # Save file if it does not exist
        if save_first:
            self.save(overwrite=True)

        output = self._reload_wpa_client()
        if 'OK' not in output:
            raise ConnectionError("An error occured during wpa_cli reconfigure %r\n\nwpa_cli Output:" + output % self)

    def get_connection_data(self):
        ifconfig_output = subprocess.check_output(['ifconfig'])

        try:
            ifconfig_parse = IfconfigParser(console_output=ifconfig_output)
            return ifconfig_parse.get_interface(self.interface)
        except Exception as e:
            print("An error occured looking for interface: " + self.interface)
            print("Stack trace: " + str(e))
            return None

    def _reload_wpa_client(self):
        # Restart connection management
        subprocess.check_output(['ifconfig', self.interface, 'up'])
        wpa_cli_output = subprocess.check_output(['wpa_cli', '-i', self.interface, 'reconfigure'],
                                                 stderr=subprocess.STDOUT).decode('utf-8')
        return wpa_cli_output

    @classmethod
    def from_string(cls, string):
        """Create a new network object by parsing a string."""
        lines = string.split("\n")
        # throw away the first and last lines, and remove indentation
        lines = [line.strip() for line in lines[1:-1]]
        opts = {}
        for line in lines:
            split = line.split("=")
            opt = split[0]
            if len(split) == 2:
                value = split[1]
            else:
                value = "=".join(split[1:])
            opts[opt] = value

        # remove the SSID from the other options and strip the quotes from it.
        ssid = opts["ssid"][1:-1]
        del opts["ssid"]

        return cls(ssid, **opts)

    @classmethod
    def find(cls, ssid, name=None,supplicant_file=WPA_SUPPLICANT_CONFIG):
        all_networks = cls.all(supplicant_file)
        # First try ssid
        for network in all_networks:
            if network.ssid == ssid:
                return network

        # If unsuccessful try name
        for network in all_networks:
            if network.nickname and name and network.nickname == name:
                return network
        return None

    @classmethod
    def all(cls, supplicant_file=WPA_SUPPLICANT_CONFIG):
        """Extract all network blocks from a file.
        Returns a list of Network objects.
        """
        with open(supplicant_file) as netfile:
            config = netfile.read()
        networks = []
        in_block = False
        netblock = []
        for line in config.split("\n"):
            line = line.strip()
            if line.startswith("#"):
                continue
            # this is really crappy "parsing" but it should work
            if line == "network={" and not in_block:
                in_block = True
            if in_block:
                netblock.append(line)
            if line == "}" and in_block:
                in_block = False
                nb = "\n".join(netblock)
                networks.append(Network.from_string(nb))
                netblock = []
        return networks

    @classmethod
    def new_network(cls, ssid, passkey="", is_open=False, id_str=None, priority=None, interface=DEFAULT_INTERFACE):
        network = cls(ssid)
        key_mgmt_type = "NONE"
        if not is_open:
            # check passphrase length
            key_mgmt_type = "WPA-PSK"
            pass_len = len(passkey)
            if pass_len < 8 or pass_len > 63:
                print("Passphrase must be 8..63 characters.")
            network.opts["psk"] = '"{}"'.format(passkey)

        # Add option params
        network.set_interface(interface)
        network.add_option("key_mgmt", key_mgmt_type)
        if id_str: network.add_option("id_str", '"{}"'.format(id_str))
        if priority: network.add_option("priority", priority)

        return network

    @classmethod
    def for_cell(cls, cell, passkey="", id_str="", priority=None, interface=DEFAULT_INTERFACE):
        return cls.new_network(cell.ssid, passkey=passkey, is_open=(not cell.encrypted), id_str=id_str,
                               priority=priority, interface=interface)