# -*- coding: utf-8 -*-
# @File  : heartbeat.py
# @Date  : 2021/2/27
# @Desc  :
import copy
import ipaddress as ipaddr
import json
import time

from Core.Handle.host import Host
from Lib.External.geoip import Geoip
from Lib.log import logger
from Lib.method import Method
from Lib.notice import Notice
from Lib.rpcclient import RpcClient
from Lib.xcache import Xcache
from Msgrpc.Handle.job import Job
from PostLateral.Handle.edge import Edge
from PostModule.Handle.postmoduleauto import PostModuleAuto
from PostModule.Handle.postmoduleresulthistory import PostModuleResultHistory


class HeartBeat(object):
    def __init__(self):
        pass

    @staticmethod
    def first_heartbeat_result():
        hosts_sorted, network_data = HeartBeat.list_hostandsession()

        result_history = PostModuleResultHistory.list_all()

        Xcache.set_heartbeat_cache_result_history(result_history)

        notices = Notice.list_notices()

        jobs = Job.list_jobs()

        bot_wait_list = Job.list_bot_wait()

        # 任务队列长度
        task_queue_length = Xcache.get_module_task_length()

        result = {
            'hosts_sorted_update': True,
            'hosts_sorted': hosts_sorted,
            'network_data_update': True,
            'network_data': network_data,
            'result_history_update': True,
            'result_history': result_history,
            'notices_update': True,
            'notices': notices,
            'task_queue_length': task_queue_length,
            'jobs_update': True,
            'jobs': jobs,
            'bot_wait_list_update': True,
            'bot_wait_list': bot_wait_list
        }

        return result

    @staticmethod
    def get_heartbeat_result():
        result = {}

        # jobs 列表 首先执行,刷新数据,删除过期任务
        jobs = Job.list_jobs()
        cache_jobs = Xcache.get_heartbeat_cache_jobs()
        if cache_jobs == jobs:
            result["jobs_update"] = False
            result["jobs"] = []
        else:
            Xcache.set_heartbeat_cache_jobs(jobs)
            result["jobs_update"] = True
            result["jobs"] = jobs

        # hosts_sorted,network_data
        hosts_sorted, network_data = HeartBeat.list_hostandsession()

        cache_hosts_sorted = Xcache.get_heartbeat_cache_hosts_sorted()
        if cache_hosts_sorted == hosts_sorted:
            result["hosts_sorted_update"] = False
            result["hosts_sorted"] = []
        else:
            Xcache.set_heartbeat_cache_hosts_sorted(hosts_sorted)
            result["hosts_sorted_update"] = True
            result["hosts_sorted"] = hosts_sorted

        cache_network_data = Xcache.get_heartbeat_cache_network_data()
        if cache_network_data == network_data:
            result["network_data_update"] = False
            result["network_data"] = []
        else:
            Xcache.set_heartbeat_cache_network_data(network_data)
            result["network_data_update"] = True
            result["network_data"] = network_data

        # result_history
        result_history = PostModuleResultHistory.list_all()

        cache_result_history = Xcache.get_heartbeat_cache_result_history()

        if cache_result_history == result_history:
            result["result_history_update"] = False
            result["result_history"] = []
        else:
            Xcache.set_heartbeat_cache_result_history(result_history)
            result["result_history_update"] = True
            result["result_history"] = result_history

        # notices
        notices = Notice.list_notices()
        cache_notices = Xcache.get_heartbeat_cache_notices()
        if cache_notices == notices:
            result["notices_update"] = False
            result["notices"] = []
        else:
            Xcache.set_heartbeat_cache_notices(notices)
            result["notices_update"] = True
            result["notices"] = notices

        # 任务队列长度
        task_queue_length = Xcache.get_module_task_length()
        result["task_queue_length"] = task_queue_length

        # bot_wait_list 列表
        bot_wait_list = Job.list_bot_wait()
        cache_bot_wait_list = Xcache.get_heartbeat_cache_bot_wait_list()
        if cache_bot_wait_list == bot_wait_list:
            result["bot_wait_list_update"] = False
            result["bot_wait_list"] = []
        else:
            Xcache.set_heartbeat_cache_bot_wait_list(bot_wait_list)
            result["bot_wait_list_update"] = True
            result["bot_wait_list"] = bot_wait_list

        return result

    @staticmethod
    def list_hostandsession():

        def short_payload(payload):
            payload = payload.replace("windows", "win")
            payload = payload.replace("linux", "lin")
            payload = payload.replace("meterpreter", "met")

            return payload

        def filter_session_by_ipaddress(ipaddress, sessions):
            result = []
            for session in sessions:
                if session.get("available"):
                    if session.get("session_host") == ipaddress:
                        result.append(session)

            return result

        hosts = Host.list_hosts()
        sessions = HeartBeat.list_sessions()

        # 初始化session列表
        for host in hosts:
            host['session'] = None

        hosts_with_session = []

        # 聚合Session和host
        for session in sessions:
            session_host = session.get("session_host")
            if session_host is None or session_host == "":
                continue

            if session.get("available"):  # 确保每个session成功后都会添加edge
                Edge.create_edge(source="255.255.255.255",
                                 target=session_host,
                                 type="online",
                                 data={"payload": "/".join(session.get("via_payload").split("/")[1:])})

            for host in hosts:
                if session_host == host.get('ipaddress'):
                    temp_host = copy.deepcopy(host)
                    temp_host['session'] = session
                    hosts_with_session.append(temp_host)
                    break
            else:  # 未找到对应的host
                # 减少新建无效的host
                if session.get("available"):
                    host_create = Host.create_host(session_host)
                else:
                    host_create = Host.create_host("255.255.255.255")
                host_create['session'] = session
                hosts_with_session.append(host_create)

        # 处理没有session的host
        for host in hosts:
            for temp_host in hosts_with_session:
                if temp_host.get("ipaddress") == host.get("ipaddress"):
                    break
            else:
                hosts_with_session.append(host)

        # 设置host的proxy信息
        # 收集所有hostip
        ipaddress_list = []
        for host in hosts_with_session:
            ipaddress_list.append(host.get('ipaddress'))

        i = 0
        for one in hosts_with_session:
            one["order_id"] = i
            i += 1

        # 开始处理network数据
        # 在这里处理是因为已经将session和host信息查找出来,直接使用即可
        # 获取nodes数据
        nodes = [
            {
                "id": '255.255.255.255',
                "data": {
                    "type": 'viper',
                },
            },
        ]
        edges = []

        # 添加scan类型的edge
        online_edge_list = Edge.list_edge(type="scan")
        for online_edge in online_edge_list:
            edge_data = {
                "source": online_edge.get("source"),
                "target": online_edge.get("target"),
                "data": {
                    "type": 'scan',
                    "method": online_edge.get("data").get("method"),
                },
            }
            edges.append(edge_data)

        for host in hosts:
            ipaddress = host.get("ipaddress")
            if ipaddress == "255.255.255.255":
                continue
            filter_sessions = filter_session_by_ipaddress(ipaddress, sessions)

            # host存在session
            if filter_sessions:
                # 加入 "包含session的主机节点"
                nodes.append({
                    "id": ipaddress,
                    "data": {
                        "type": 'host',
                        "sessionnum": len(filter_sessions),
                        "platform": filter_sessions[0].get("platform"),
                    },
                })
                for session in filter_sessions:
                    sid = session.get("id")
                    platform = session.get("platform")
                    payload = "/".join(session.get("via_payload").split("/")[1:])
                    # 主机节点连接到viper节点
                    edges.append({
                        "source": '255.255.255.255',
                        "target": ipaddress,
                        "data": {
                            "type": 'session',
                            "payload": short_payload(payload),
                        },
                    })

                    # 加入session节点
                    sesison_node_id = f"SID - {sid}"
                    nodes.append({
                        "id": sesison_node_id,
                        "data": {
                            "type": 'session',
                            "sid": sid,
                            "platform": platform,
                        },
                    })

                    # 主机节点连接到session节点
                    edges.append({
                        "source": ipaddress,
                        "target": sesison_node_id,
                        "data": {
                            "type": 'session',
                            "payload": short_payload(payload),
                        },
                    })

                    # route edge
                    routes = session.get("routes")
                    sid = session.get("id")
                    for route in routes:
                        ipnetwork = ipaddr.ip_network(f"{route.get('subnet')}/{route.get('netmask')}", strict=False)
                        for host_in in hosts:
                            ipaddress_in = host_in.get("ipaddress")
                            if ipaddress_in == "255.255.255.255" or ipaddress_in == ipaddress:
                                continue
                            if ipaddr.ip_address(ipaddress_in) in ipnetwork:
                                edges.append({
                                    "source": sesison_node_id,
                                    "target": ipaddress_in,
                                    "data": {
                                        "type": "route",
                                        "sid": sid,
                                    },
                                })

            else:
                # host不存在session
                nodes.append({
                    "id": ipaddress,
                    "data": {
                        "type": 'host',
                    },
                })

                # 查看是否存在online类型的edge
                online_edge_list = Edge.list_edge(target=ipaddress, type="online")
                for online_edge in online_edge_list:
                    edge_data = {
                        "source": '255.255.255.255',
                        "target": ipaddress,
                        "data": {
                            "type": 'online',
                            "payload": short_payload(online_edge.get("data").get("payload")),
                        },
                    }
                    edges.append(edge_data)
        network_data = {"nodes": nodes, "edges": edges}
        return hosts_with_session, network_data

    @staticmethod
    def list_sessions():
        # 更新session的监听配置
        uuid_msfjobid = {}
        msfjobs = Job.list_msfrpc_jobs()
        if msfjobs is not None:
            for jobid in msfjobs:
                datastore = msfjobs[jobid].get("datastore")
                if datastore is not None:
                    uuid_msfjobid[msfjobs[jobid]["uuid"]] = {"job_id": int(jobid),
                                                             "PAYLOAD": datastore.get("PAYLOAD"),
                                                             "LPORT": datastore.get("LPORT"),
                                                             "LHOST": datastore.get("LHOST"),
                                                             "RHOST": datastore.get("RHOST")}

        sessions_available_count = 0
        sessions = []
        session_info_dict = RpcClient.call(Method.SessionList, timeout=3)
        if session_info_dict is None:
            return []

        if session_info_dict.get('error'):
            logger.warning(session_info_dict.get('error_string'))
            return []

        sessionhosts = []
        for session_id_str in session_info_dict.keys():
            session_info = session_info_dict.get(session_id_str)
            if session_info is not None:
                one_session = {}
                try:
                    one_session['id'] = int(session_id_str)
                except Exception as E:
                    logger.warning(E)
                    continue

                # 处理linux的no-user问题
                if str(session_info.get('info')).split(' @ ')[0] == "no-user":
                    session_info['info'] = session_info.get('info')[10:]

                # 处理session对应监听问题
                one_session['exploit_uuid'] = session_info.get('exploit_uuid')
                if uuid_msfjobid.get(session_info.get('exploit_uuid')) is None:
                    one_session['job_info'] = {"job_id": -1,
                                               "PAYLOAD": None,
                                               "LPORT": None,
                                               "LHOST": None,
                                               "RHOST": None}
                else:
                    one_session['job_info'] = uuid_msfjobid.get(session_info.get('exploit_uuid'))

                one_session['type'] = session_info.get('type')
                one_session['session_host'] = session_info.get('session_host')
                one_session['tunnel_local'] = session_info.get('tunnel_local')
                one_session['tunnel_peer'] = session_info.get('tunnel_peer')
                one_session['tunnel_peer_ip'] = session_info.get('tunnel_peer').split(":")[0]
                one_session['tunnel_peer_locate'] = Geoip.get_city(session_info.get('tunnel_peer').split(":")[0])
                one_session['via_exploit'] = session_info.get('via_exploit')
                one_session['via_payload'] = session_info.get('via_payload')
                one_session['tunnel_peer_ip'] = session_info.get('tunnel_peer').split(":")[0]
                one_session['tunnel_peer_locate'] = Geoip.get_city(session_info.get('tunnel_peer').split(":")[0])
                one_session['uuid'] = session_info.get('uuid')
                one_session['platform'] = session_info.get('platform')
                one_session['last_checkin'] = session_info.get('last_checkin') // 5 * 5
                one_session['fromnow'] = (int(time.time()) - session_info.get('last_checkin')) // 5 * 5
                one_session['info'] = session_info.get('info')
                one_session['arch'] = session_info.get('arch')

                try:
                    one_session['user'] = str(session_info.get('info')).split(' @ ')[0]
                    one_session['computer'] = str(session_info.get('info')).split(' @ ')[1]
                except Exception as _:
                    one_session['user'] = "Initializing"
                    one_session['computer'] = "Initializing"
                    one_session['advanced_info'] = {"sysinfo": {}, "username": "Initializing"}
                    one_session['os'] = None
                    one_session['load_powershell'] = False
                    one_session['load_python'] = False
                    one_session['routes'] = []
                    one_session['isadmin'] = False
                    one_session['available'] = False  # 是否初始化完成
                    sessions.append(one_session)
                    continue

                one_session['load_powershell'] = session_info.get('load_powershell')
                one_session['load_python'] = session_info.get('load_python')

                advanced_info = session_info.get('advanced_info')
                one_session['advanced_info'] = advanced_info

                try:
                    one_session['os'] = advanced_info.get("sysinfo").get("OS")
                    one_session['os_short'] = advanced_info.get("sysinfo").get("OS").split("(")[0]
                except Exception as _:
                    one_session['os'] = None
                    one_session['os_short'] = None

                try:
                    one_session['isadmin'] = advanced_info.get("sysinfo").get("IsAdmin")
                    if session_info.get('platform').lower().startswith('linux'):
                        if "uid=0" in one_session['info'].lower():
                            one_session['isadmin'] = True
                except Exception as _:
                    one_session['isadmin'] = None

                try:
                    one_session['pid'] = advanced_info.get("sysinfo").get("Pid")
                except Exception as _:
                    one_session['pid'] = -1  # linux暂时不支持展示pid

                routestrlist = session_info.get('routes')
                one_session['routes'] = []
                try:
                    if isinstance(routestrlist, list):
                        for routestr in routestrlist:
                            routestr.split('/')
                            tmpdict = {"subnet": routestr.split('/')[0], 'netmask': routestr.split('/')[1]}
                            one_session['routes'].append(tmpdict)
                except Exception as E:
                    logger.error(E)
                one_session['available'] = True
                sessions.append(one_session)

                # session监控统计信息
                sessionhosts.append(session_info.get('session_host'))
                sessions_available_count += 1

        def session_host_key(item):
            try:
                ip = item.get("session_host")
                result = tuple(int(part) for part in ip.split('.'))
            except Exception as _:
                return 0, 0, 0, 0
            return result

        def session_cout_by_session_host(session, sessions):
            count = 0
            sesison_host = session.get("session_host")
            for tmp in sessions:
                if tmp.get("available"):
                    if tmp.get("session_host") == sesison_host:
                        count += 1
            return count

        sessions = sorted(sessions, key=session_host_key)

        # 获取新增的session配置信息
        add_session_dict = Xcache.update_session_list(sessions)
        # session监控功能
        if Xcache.get_sessionmonitor_conf().get("flag"):
            for session_uuid in add_session_dict:
                Notice.send_sms(f"新增session: {json.dumps(add_session_dict.get(session_uuid))}")

        # postmoduleauto功能
        if Xcache.get_postmodule_auto_conf().get("flag"):
            max_session = Xcache.get_postmodule_auto_conf().get("max_session")
            if max_session is None:
                max_session = 3
            if max_session < 3 or max_session > 5:
                max_session = 3

            for session_uuid in add_session_dict:
                if session_cout_by_session_host(add_session_dict.get(session_uuid), sessions) >= max_session:
                    continue

                PostModuleAuto.send_task(json.dumps(add_session_dict.get(session_uuid)))
                Notice.send_info(f"发送自动编排任务: SID {add_session_dict.get(session_uuid).get('id')}")

        return sessions
