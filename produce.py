#!/usr/bin/env python3
import argparse
import csv
from ipaddress import IPv4Network, IPv6Network
import math
from datetime import datetime
import urllib.request
from pathlib import Path

urllib.request.urlretrieve("https://ftp.apnic.net/stats/apnic/delegated-apnic-latest", "delegated-apnic-latest")
urllib.request.urlretrieve("https://raw.githubusercontent.com/17mon/china_ip_list/master/china_ip_list.txt", "china_ip_list.txt")


# 创建参数解析器对象，设置脚本描述
parser = argparse.ArgumentParser(description='Generate non-China routes for BIRD.')

# 添加 --exclude 参数
parser.add_argument('--exclude',         # 参数名称
                   metavar='CIDR',      # 参数值的占位符名称（显示在帮助信息）
                   type=str,            # 参数类型为字符串
                   nargs='*',           # 接受零个或多个参数值（多个CIDR）
                   help='IPv4 ranges to exclude in CIDR format')  # 帮助说明

# 添加 --next 参数
parser.add_argument('--next',            # 参数名称
                   default="g2/0",       # 默认值（当不指定该参数时使用）
                   metavar="INTERFACE OR IP",  # 参数值的占位符名称
                   help='next hop for where non-China IP address, this is usually the tunnel interface')  # 帮助说明

# 添加 --ipv4-list 参数
parser.add_argument('--ipv4-list',       # 参数名称
                   choices=['apnic', 'ipip'],  # 允许的值列表（只能选这两个值）
                   default=['apnic', 'ipip'],  # 默认同时使用两个列表
                   nargs='*',           # 接受零个或多个参数值（可同时选择多个列表）
                   help='IPv4 lists to use when subtracting China based IP, multiple lists can be used at the same time (default: apnic ipip)')  # 帮助说明

# 解析命令行参数
args = parser.parse_args()


class Node:
    def __init__(self, cidr, parent=None):
        self.cidr = cidr
        self.child = []
        self.dead = False
        self.parent = parent

    def __repr__(self):
        return "<Node %s>" % self.cidr

def dump_tree(lst, ident=0):
    for n in lst:
        print("+" * ident + str(n))
        dump_tree(n.child, ident + 1)

def dump_bird(lst, f, write_line_func):
    for n in lst:
        if n.dead:
            continue

        if len(n.child) > 0:
            dump_bird(n.child, f, write_line_func)

        elif not n.dead:
            # 将 IPv4Network 对象转换为字符串（例如 "0.0.0.0/8"）
            cidr_str = str(n.cidr)  # 关键：先转字符串
            # 替换斜杠为空格（例如 "0.0.0.0 8"）
            converted_cidr = cidr_str.replace("/", " ")
            write_line_func(f, converted_cidr)


def write_format1(f, converted_cidr):
    f.write(' ;ip route-static %s %s 192.168.100.230' % (converted_cidr, args.next))
def write_format2(f, converted_cidr):
    f.write(' ;undo ip route-static %s %s 192.168.100.230' % (converted_cidr, args.next))


RESERVED = [
    IPv4Network('0.0.0.0/8'),
    IPv4Network('10.0.0.0/8'),
    IPv4Network('127.0.0.0/8'),
    IPv4Network('169.254.0.0/16'),
    IPv4Network('172.16.0.0/12'),
    IPv4Network('192.0.0.0/29'),
    IPv4Network('192.0.0.170/31'),
    IPv4Network('192.0.2.0/24'),
    IPv4Network('192.168.0.0/16'),
    IPv4Network('198.18.0.0/15'),
    IPv4Network('198.51.100.0/24'),
    IPv4Network('203.0.113.0/24'),
    IPv4Network('240.0.0.0/4'),
    IPv4Network('255.255.255.255/32'),
    IPv4Network('169.254.0.0/16'),
    IPv4Network('127.0.0.0/8'),
    IPv4Network('224.0.0.0/4'),
    IPv4Network('100.64.0.0/10'),
]
RESERVED_V6 = []
if args.exclude:
    for e in args.exclude:
        if ":" in e:
            RESERVED_V6.append(IPv6Network(e))

        else:
            RESERVED.append(IPv4Network(e))

IPV6_UNICAST = IPv6Network('2000::/3')

def subtract_cidr(sub_from, sub_by):
    for cidr_to_sub in sub_by:
        for n in sub_from:
            if n.cidr == cidr_to_sub:
                n.dead = True
                break

            if n.cidr.supernet_of(cidr_to_sub):
                if len(n.child) > 0:
                    subtract_cidr(n.child, sub_by)

                else:
                    n.child = [Node(b, n) for b in n.cidr.address_exclude(cidr_to_sub)]

                break

root = []
root_v6 = [Node(IPV6_UNICAST)]

with open("ipv4-address-space.csv", newline='') as f:
    f.readline() # skip the title

    reader = csv.reader(f, quoting=csv.QUOTE_MINIMAL)
    for cidr in reader:
        if cidr[5] == "ALLOCATED" or cidr[5] == "LEGACY":
            block = cidr[0]
            cidr = "%s.0.0.0%s" % (block[:3].lstrip("0"), block[-2:], )
            root.append(Node(IPv4Network(cidr)))

with open("delegated-apnic-latest") as f:
    for line in f:
        if 'apnic' in args.ipv4_list and "apnic|CN|ipv4|" in line:
            line = line.split("|")
            a = "%s/%d" % (line[3], 32 - math.log(int(line[4]), 2), )
            a = IPv4Network(a)
            subtract_cidr(root, (a,))

        elif "apnic|CN|ipv6|" in line:
            line = line.split("|")
            a = "%s/%s" % (line[3], line[4])
            a = IPv6Network(a)
            subtract_cidr(root_v6, (a,))

if 'ipip' in args.ipv4_list:
    with open("china_ip_list.txt") as f:
        for line in f:
            line = line.strip('\n')
            a = IPv4Network(line)
            subtract_cidr(root, (a,))

# get rid of reserved addresses
subtract_cidr(root, RESERVED)
# get rid of reserved addresses
subtract_cidr(root_v6, RESERVED_V6)


current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
with open("routes4.py", "w") as f:
    # 添加头部内容
    f.write(f"# Auto-generated on: {current_time}\n")
    f.write("import comware\n")
    f.write("comware.CLI('system-view")
    # 生成主体路由配置
    dump_bird(root, f, write_format1)
    # 添加尾部内容
    f.write("')")

with open("unroutes4.py", "w") as f:
    # 添加头部内容
    f.write(f"# Auto-generated on: {current_time}\n")
    f.write("import comware\n")
    f.write("comware.CLI('system-view")
    # 生成主体路由配置
    dump_bird(root, f, write_format2)
    # 添加尾部内容
    f.write("')")


# with open("routes6.conf", "w") as f:
#     dump_bird(root_v6, f)

[Path(f).unlink(missing_ok=True) for f in ["delegated-apnic-latest", "china_ip_list.txt"]]