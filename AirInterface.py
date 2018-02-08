import random

import Global
import PropagationModel
from Location import Location
from Gateway import Gateway
from LoRaPacket import UplinkMessage
import matplotlib.pyplot as plt

from SNRModel import SNRModel


class AirInterface:
    def __init__(self, gateway: Gateway, prop_model: PropagationModel, snr_model: SNRModel, env):
        self.num_of_packets_collided = 0
        self.prop_measurements = {}
        self.num_of_packets_send = 0
        self.gateway = gateway
        self.packages_in_air = list()
        self.color_per_node = dict()
        self.prop_model = prop_model
        self.snr_model = snr_model
        self.env = env

    @staticmethod
    def frequency_collision(p1: UplinkMessage, p2: UplinkMessage):
        """frequencyCollision, conditions
                |f1-f2| <= 120 kHz if f1 or f2 has bw 500
                |f1-f2| <= 60 kHz if f1 or f2 has bw 250
                |f1-f2| <= 30 kHz if f1 or f2 has bw 125
        """

        p1_freq = p1.lora_param.freq
        p2_freq = p2.lora_param.freq

        p1_bw = p1.lora_param.bw
        p2_bw = p2.lora_param.bw

        if abs(p1_freq - p2_freq) <= 120 and (p1_bw == 500 or p2_bw == 500):
            if Global.Config.PRINT_ENABLED:
                print("frequency coll 500")
            return True
        elif abs(p1_freq - p2_freq) <= 60 and (p1_bw == 250 or p2_bw == 250):
            if Global.Config.PRINT_ENABLED:
                print("frequency coll 250")
            return True
        elif abs(p1_freq - p2_freq) <= 30 and (p1_bw == 125 or p2_bw == 125):
            if Global.Config.PRINT_ENABLED:
                print("frequency coll 125")
            return True

        if Global.Config.PRINT_ENABLED:
            print("no frequency coll")
        return False

    @staticmethod
    def sf_collision(p1: UplinkMessage, p2: UplinkMessage):
        #
        # sfCollision, conditions
        #
        #       sf1 == sf2
        #
        if p1.lora_param.sf == p2.lora_param.sf:
            if Global.Config.PRINT_ENABLED:
                print("collision sf node {} and node {}".format(p1.node.id, p2.node.id))
            return True
        if Global.Config.PRINT_ENABLED:
            print("no sf collision")
        return False

    @staticmethod
    def timing_collision(me: UplinkMessage, other: UplinkMessage):
        # packet p1 collides with packet p2 when it overlaps in its critical section

        sym_duration = 2 ** me.lora_param.sf / (1.0 * me.lora_param.bw)
        num_preamble = 8
        critical_section_start = me.start_on_air + sym_duration * (num_preamble - 5)
        critical_section_end = me.start_on_air + me.my_time_on_air()

        other_end = other.start_on_air + other.my_time_on_air()

        if other_end < critical_section_start or other.start_on_air > critical_section_end:
            # all good
            return False
        else:
            # timing collision
            return True

    @staticmethod
    def power_collision(me: UplinkMessage, other: UplinkMessage) -> bool:
        power_threshold = 6  # dB
        if Global.Config.PRINT_ENABLED:
            print(
                "pwr: node {0.node.id} {0.rss:3.2f} dBm node {1.node.id} {1.rss:3.2f} dBm; diff {2:3.2f} dBm".format(me,
                                                                                                                     other,
                                                                                                                     round(
                                                                                                                         me.rss - other.rss,
                                                                                                                         2)))
        if abs(me.rss - other.rss) < power_threshold:
            if Global.Config.PRINT_ENABLED:
                print("collision pwr both node {} and node {} (too close to each other)".format(me.node.id,
                                                                                                other.node.id))
            return True

    def collision(self, packet) -> bool:
        if Global.Config.PRINT_ENABLED:
            print("CHECK node {} (sf:{} bw:{} freq:{:.6e}) #others: {}".format(
                packet.node.id, packet.lora_param.sf, packet.lora_param.bw, packet.lora_param.freq,
                len(self.packages_in_air)))
        if packet.collided:
            return True
        for other in self.packages_in_air:
            if other.node.id != packet.node.id:
                if Global.Config.PRINT_ENABLED:
                    print(">> node {} (sf:{} bw:{} freq:{:.6e})".format(
                        other.node.id, other.lora_param.sf, other.lora_param.bw,
                        other.lora_param.freq))
                if AirInterface.frequency_collision(packet, other):
                    if AirInterface.sf_collision(packet, other):
                        if AirInterface.timing_collision(packet, other):
                            if AirInterface.power_collision(packet, other):
                                packet.collided = True
        return packet.collided

    color_values = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f']

    def packet_in_air(self, packet: UplinkMessage):
        self.num_of_packets_send += 1
        id = packet.node.id
        if id not in self.color_per_node:
            self.color_per_node[id] = '#' + random.choice(AirInterface.color_values) + random.choice(
                AirInterface.color_values) + random.choice(AirInterface.color_values) + random.choice(
                AirInterface.color_values) + random.choice(AirInterface.color_values) + random.choice(
                AirInterface.color_values)

        from_node = packet.node
        node_id = from_node.id
        rss = self.prop_model.tp_to_rss(from_node.location.indoor, packet.lora_param.tp,
                                        Location.distance(self.gateway.location, packet.node.location))
        if node_id not in self.prop_measurements:
            self.prop_measurements[node_id] = {'rss': [], 'snr': [], 'time': []}
        packet.rss = rss
        snr = self.snr_model.rss_to_snr(rss)
        packet.snr = snr

        self.prop_measurements[node_id]['time'].append(self.env.now)
        self.prop_measurements[node_id]['rss'].append(rss)
        self.prop_measurements[node_id]['snr'].append(snr)

        self.packages_in_air.append(packet)

    def packet_received(self, packet: UplinkMessage) -> bool:
        """Packet has fully received by the gateway
            This method checks if this packet has collided
            :return bool (True collided or False not collided)"""

        collided = self.collision(packet)
        if collided:
            self.num_of_packets_collided += 1
        # Do not remove the packet from the air
        # this is used to be certain that the collision algorithm works
        # self.packages_in_air.remove(packet)
        return collided

    def plot_packets_in_air(self):
        plt.figure()
        ax = plt.gca()
        plt.axis('off')
        ax.grid(False)
        for package in self.packages_in_air:
            node_id = package.node.id
            plt.hlines(package.lora_param.freq, package.start_on_air, package.start_on_air + package.my_time_on_air(),
                       color=self.color_per_node[node_id],
                       linewidth=2.0)
        plt.show()

    def log(self):
        print('Total number of packets in the air {}'.format(self.num_of_packets_send))
        print('Total number of packets collided {} {:2.2f}%'.format(self.num_of_packets_collided,
                                                                    self.num_of_packets_collided * 100 / self.num_of_packets_send))

    def get_prop_measurements(self, node_id):
        return self.prop_measurements[node_id]
