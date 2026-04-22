"""
CURL 命令解析器
将 curl 命令解析为结构化的请求配置，支持动态注入登录凭证
"""

import json
import logging
import re
import shlex
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode

logger = logging.getLogger('finance-tools.curl-parser')


class CurlParser:
    """解析 CURL 命令，支持凭证动态注入"""

    def parse(self, curl_command: str) -> dict:
        """
        解析 CURL 命令为结构化配置

        支持的 curl 选项:
        - -X / --request: HTTP 方法
        - -H / --header: 请求头
        - -d / --data / --data-raw / --data-binary: 请求体
        - -F / --form: 表单数据
        - -k / --insecure: 忽略 SSL
        - -b / --cookie: Cookie (会被移除，改为动态注入)
        - --url: URL

        Args:
            curl_command: curl 命令字符串

        Returns:
            {
                'method': 'GET',
                'url': 'https://...',
                'headers': {...},
                'params': {...},
                'body': '',
                'inject_credential': True
            }
        """
        if not curl_command or not curl_command.strip():
            return self._empty_config()

        # 预处理：移除换行续行符
        cmd = curl_command.replace('\\\n', ' ').replace('\\\r\n', ' ')
        # 移除多余空白
        cmd = re.sub(r'\s+', ' ', cmd).strip()

        # 尝试多种解析策略
        try:
            return self._parse_with_shlex(cmd)
        except Exception as e:
            logger.warning(f"shlex parse failed: {e}, trying regex fallback")
            try:
                return self._parse_with_regex(cmd)
            except Exception as e2:
                logger.error(f"All CURL parse methods failed: {e2}")
                return self._empty_config()

    def _parse_with_shlex(self, cmd: str) -> dict:
        """使用 shlex 解析 curl 命令"""
        tokens = shlex.split(cmd)

        # 去掉开头的 curl
        if tokens and tokens[0].lower() == 'curl':
            tokens = tokens[1:]

        method = 'GET'
        url = ''
        headers = {}
        body = ''
        inject_credential = True
        has_explicit_method = False

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token in ('-X', '--request'):
                i += 1
                if i < len(tokens):
                    method = tokens[i].upper()
                    has_explicit_method = True

            elif token in ('-H', '--header'):
                i += 1
                if i < len(tokens):
                    header_val = tokens[i]
                    if ':' in header_val:
                        key, _, value = header_val.partition(':')
                        key = key.strip()
                        value = value.strip()
                        # Cookie 头标记为需要动态注入
                        if key.lower() == 'cookie':
                            inject_credential = True
                            # 不保存原始 Cookie，运行时动态注入
                        else:
                            headers[key] = value

            elif token in ('-d', '--data', '--data-raw', '--data-binary'):
                i += 1
                if i < len(tokens):
                    body = tokens[i]
                    if not has_explicit_method:
                        method = 'POST'

            elif token in ('-F', '--form'):
                i += 1
                if i < len(tokens):
                    if not has_explicit_method:
                        method = 'POST'
                    # form data 暂存到 body
                    if body:
                        body += '&' + tokens[i]
                    else:
                        body = tokens[i]

            elif token in ('-b', '--cookie'):
                i += 1
                # Cookie 跳过，运行时动态注入
                inject_credential = True

            elif token in ('-k', '--insecure'):
                # 忽略 SSL 验证标志，httpx 默认行为
                pass

            elif token in ('--compressed', '-L', '--location', '-s', '--silent',
                           '-S', '--show-error', '-v', '--verbose'):
                # 忽略这些标志
                pass

            elif token in ('-o', '--output', '-u', '--user', '--connect-timeout',
                           '-m', '--max-time', '--retry', '-w', '--write-out'):
                # 需要参数的标志，跳过参数
                i += 1

            elif token.startswith('--url='):
                url = token.split('=', 1)[1]

            elif not token.startswith('-') and not url:
                # 第一个非选项参数是 URL
                url = token

            i += 1

        # 解析 URL 中的查询参数
        parsed_url, params = self._parse_url_params(url)

        # 尝试解析 body 为 JSON
        parsed_body = self._try_parse_json_body(body)

        return {
            'method': method,
            'url': parsed_url,
            'headers': headers,
            'params': params,
            'body': parsed_body if parsed_body else body,
            'inject_credential': inject_credential,
        }

    def _parse_with_regex(self, cmd: str) -> dict:
        """正则表达式备用解析"""
        method = 'GET'
        url = ''
        headers = {}
        body = ''
        inject_credential = True

        # 提取方法
        method_match = re.search(r'-X\s+(\w+)', cmd)
        if method_match:
            method = method_match.group(1).upper()

        # 提取 URL
        url_match = re.search(r"""['"]?(https?://[^\s'"]+)['"]?""", cmd)
        if url_match:
            url = url_match.group(1)

        # 提取 headers
        header_matches = re.findall(r"""-H\s+['"](.+?):\s*(.+)['"]""", cmd)
        for key, value in header_matches:
            if key.strip().lower() == 'cookie':
                inject_credential = True
            else:
                headers[key.strip()] = value.strip()

        # 提取 body
        data_match = re.search(r"""(-d|--data|--data-raw|--data-binary)\s+['"](.+?)['"]""", cmd)
        if data_match:
            body = data_match.group(2)
            if method == 'GET':
                method = 'POST'

        parsed_url, params = self._parse_url_params(url)

        return {
            'method': method,
            'url': parsed_url,
            'headers': headers,
            'params': params,
            'body': body,
            'inject_credential': inject_credential,
        }

    def build_request_config(self, task: dict, cookie_header: str = '') -> dict:
        """
        根据任务配置和凭证构建实际的 HTTP 请求配置
        支持通过 field_mapping 动态替换请求中的参数值

        Args:
            task: 任务配置（来自数据库，包含 url/headers/params/body/field_mapping）
            cookie_header: 登录凭证 Cookie 字符串

        Returns:
            httpx 请求配置
        """
        logger.info(f"[build_request_config] start, task id={task.get('id')}, url={task.get('url')}, method={task.get('method')}")

        headers = {}
        try:
            raw_headers = task.get('headers', '{}')
            logger.debug(f"[build_request_config] raw_headers type={type(raw_headers).__name__}, value={str(raw_headers)[:200]}")
            headers = json.loads(raw_headers) if isinstance(raw_headers, str) else raw_headers
            if not isinstance(headers, dict):
                logger.warning(f"[build_request_config] headers is not dict (type={type(headers).__name__}), converting to empty dict. value={str(headers)[:200]}")
                headers = {}
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[build_request_config] failed to parse headers: {e}")
            headers = {}

        params = {}
        try:
            raw_params = task.get('params', '{}')
            logger.debug(f"[build_request_config] raw_params type={type(raw_params).__name__}, value={str(raw_params)[:200]}")
            params = json.loads(raw_params) if isinstance(raw_params, str) else raw_params
            if not isinstance(params, dict):
                logger.warning(f"[build_request_config] params is not dict (type={type(params).__name__}), converting to empty dict. value={str(params)[:200]}")
                params = {}
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[build_request_config] failed to parse params: {e}")
            params = {}

        # 获取字段映射（动态替换规则）
        field_mapping = {}
        try:
            raw_fm = task.get('field_mapping', '{}')
            logger.debug(f"[build_request_config] raw_field_mapping type={type(raw_fm).__name__}, value={str(raw_fm)[:200]}")
            field_mapping = json.loads(raw_fm) if isinstance(raw_fm, str) else raw_fm
            if not isinstance(field_mapping, dict):
                logger.warning(f"[build_request_config] field_mapping is not dict (type={type(field_mapping).__name__}), converting to empty dict. value={str(field_mapping)[:200]}")
                field_mapping = {}
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[build_request_config] failed to parse field_mapping: {e}")
            field_mapping = {}

        if field_mapping:
            logger.info(f"Field mapping applied: {list(field_mapping.keys())}")

            # 用映射值替换 URL 查询参数
            for key, value in field_mapping.items():
                if key in params:
                    params[key] = value

            # 用映射值替换 Headers 中的同名键
            for key, value in field_mapping.items():
                if key in headers:
                    headers[key] = value

        # 动态注入凭证
        if task.get('inject_credential', 1) and cookie_header:
            headers['Cookie'] = cookie_header

        # 补充 User-Agent
        if 'User-Agent' not in headers and 'user-agent' not in headers:
            headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

        # 补充 Accept
        if 'Accept' not in headers and 'accept' not in headers:
            headers['Accept'] = 'application/json, text/html, */*'

        method = task.get('method', 'GET').upper()
        body = task.get('body', '')

        # 如果 body 是字符串格式的 JSON，尝试解析
        request_kwargs = {
            'method': method,
            'url': task.get('url', ''),
            'headers': headers,
            'params': params,
        }

        if body and method in ('POST', 'PUT', 'PATCH'):
            content_type = headers.get('Content-Type', headers.get('content-type', ''))
            if 'application/json' in content_type or body.strip().startswith('{') or body.strip().startswith('['):
                try:
                    body_json = json.loads(body) if isinstance(body, str) else body
                    # 用字段映射替换 body 中的同名键（支持嵌套路径如 "data.startDate"）
                    self._apply_field_mapping_to_body(field_mapping, body_json)
                    request_kwargs['json'] = body_json
                except (json.JSONDecodeError, TypeError):
                    request_kwargs['data'] = body
            else:
                request_kwargs['data'] = body

        return request_kwargs

    def _apply_field_mapping_to_body(self, field_mapping: dict, body_obj: any, prefix: str = '') -> None:
        """
        递归地将字段映射应用到 JSON body 上
        支持点号分隔的嵌套路径，如 "data.startDate"
        也支持直接匹配顶层和嵌套的键名
        """
        if not isinstance(body_obj, (dict, list)) or not field_mapping:
            return

        if isinstance(body_obj, dict):
            for key in list(body_obj.keys()):
                full_key = f"{prefix}.{key}" if prefix else key

                # 精确匹配完整路径或仅键名
                if full_key in field_mapping:
                    body_obj[key] = field_mapping[full_key]
                elif key in field_mapping:
                    body_obj[key] = field_mapping[key]
                elif isinstance(body_obj[key], (dict, list)):
                    self._apply_field_mapping_to_body(field_mapping, body_obj[key], full_key)

        elif isinstance(body_obj, list):
            for i, item in enumerate(body_obj):
                if isinstance(item, (dict, list)):
                    self._apply_field_mapping_to_body(field_mapping, item, f"{prefix}[{i}]")

    def _parse_url_params(self, url: str) -> tuple[str, dict]:
        """将 URL 中的查询参数提取出来"""
        if not url:
            return '', {}

        try:
            parsed = urlparse(url)
            if parsed.query:
                params = {}
                for key, values in parse_qs(parsed.query).items():
                    params[key] = values[0] if len(values) == 1 else values
                # 重建不含参数的 URL
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                return clean_url, params
            return url, {}
        except Exception:
            return url, {}

    def _try_parse_json_body(self, body: str) -> Optional[str]:
        """尝试将 body 解析为 JSON 后重新格式化"""
        if not body:
            return None
        try:
            parsed = json.loads(body)
            return json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return body

    # ==================== 响应数据提取 ====================

    def extract_data(self, response_json: any, extract_config: dict) -> list[dict]:
        """
        从响应 JSON 中按配置提取数据

        Args:
            response_json: API 响应的 JSON 数据（dict 或 list）
            extract_config: 提取配置
                {
                    "list_path": "data.records",      // 列表在响应中的 JSON 路径，空则取整个响应
                    "fields": {                        // 要提取的字段映射 {"目标字段名": "源路径"}
                        "orderNo": "orderNo",
                        "amount": "payAmount",
                        "date": "createTime"
                    }
                }

        Returns:
            提取出的数据列表 [ {field1: val, field2: val}, ... ]
        """
        if not isinstance(response_json, (dict, list)):
            logger.warning(f"[extract_data] response_json is not dict/list: type={type(response_json).__name__}, value={str(response_json)[:200]}")
            return [{'raw': str(response_json)}]

        list_path = (extract_config or {}).get('list_path', '')
        fields = (extract_config or {}).get('fields', {})
        # 支持 list 格式的 fields: [{"target": "名称", "source": "batchName"}, ...] → {"名称": "batchName"}
        if isinstance(fields, list):
            converted = {}
            for item in fields:
                if isinstance(item, dict) and 'target' in item and 'source' in item:
                    converted[item['target']] = item['source']
                elif isinstance(item, dict) and len(item) == 1:
                    # 兼容 {"目标字段名": "源路径"} 单项
                    converted.update(item)
            logger.info(f"[extract_data] fields list→dict 转换: {len(fields)}项 → {len(converted)}项")
            fields = converted
        if not isinstance(fields, dict):
            logger.warning(f"[extract_data] fields is not dict (type={type(fields).__name__}): {str(fields)[:200]}, treating as empty")
            fields = {}
        logger.info(f"[extract_data] list_path='{list_path}', fields={list(fields.keys())}, response_type={type(response_json).__name__}")

        # 获取数据列表
        data_list = None

        if isinstance(response_json, dict):
            if list_path:
                # 按路径提取列表
                data_list = self._get_value_by_path(response_json, list_path)
                logger.debug(f"[extract_data] value at list_path '{list_path}': type={type(data_list).__name__}")
                if not isinstance(data_list, list):
                    logger.warning(f"[extract_data] list_path '{list_path}' 返回的不是列表: type={type(data_list).__name__}, value={str(data_list)[:200]}")
                    # 如果路径返回的不是列表但不是None，包装成单元素列表
                    if data_list is not None:
                        data_list = [data_list]
            else:
                data_list = response_json  # 整个响应作为单个数据项
        elif isinstance(response_json, list):
            data_list = response_json

        if not data_list:
            logger.debug(f"[extract_data] data_list is empty, returning []")
            return []

        if isinstance(data_list, dict) and not fields:
            return [data_list]

        # 如果没有字段配置且是列表，原样返回
        if not fields and isinstance(data_list, list):
            return data_list if all(isinstance(item, dict) for item in data_list) \
                   else [{'raw': item} for item in data_list]

        logger.debug(f"[extract_data] iterating {len(data_list)} items with {len(fields)} field mappings")
        result = []
        for idx, item in enumerate(data_list):
            if not isinstance(item, dict):
                logger.debug(f"[extract_data] item[{idx}] is not dict: type={type(item).__name__}, wrapping as raw")
                result.append({'raw': item})
                continue

            row = {}
            for target_field, source_path in fields.items():
                value = self._get_value_by_path(item, source_path)
                row[target_field] = value
            result.append(row)

        return result

    def _get_value_by_path(self, obj: any, path: str) -> any:
        """
        从嵌套对象中按路径获取值
        支持点号分隔的路径：data.list[0].name
        """
        if not obj or not path:
            return None

        current = obj
        parts = re.split(r'\.|\[|\]', path)
        parts = [p for p in parts if p]  # 过滤空字符串

        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, (list, tuple)):
                try:
                    idx = int(part)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None

        return current

    def _find_first_value(self, obj: any, key: str) -> any:
        """递归搜索字典树，找到第一个与 key 匹配的叶子值"""
        if isinstance(obj, dict):
            if key in obj:
                val = obj[key]
                # 只返回简单类型的值（非嵌套对象）
                if not isinstance(val, (dict, list)):
                    return val
            for v in obj.values():
                result = self._find_first_value(v, key)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_first_value(item, key)
                if result is not None:
                    return result
        return None

    def _set_value_by_path(self, obj: dict, path: str, value: any) -> None:
        """
        按嵌套路径设置值，自动创建中间字典
        支持点号分隔的路径：data.page.pageIndex
        如果路径中不包含点号（如 'pageIndex'），则递归搜索并修改所有同名叶子节点
        """
        if not obj or not path:
            return

        if '.' in path:
            # 显式嵌套路径：逐层深入设置
            parts = re.split(r'\.|\[|\]', path)
            parts = [p for p in parts if p]
            if not parts:
                return

            current = obj
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    current[part] = {}  # 覆盖非字典值
                current = current[part]

            current[parts[-1]] = value
        else:
            # 简单字段名：递归搜索所有同名叶子节点并更新
            self._set_nested_value_recursive(obj, path, value)

    def _set_nested_value_recursive(self, node: any, key: str, value: any) -> bool:
        """递归搜索字典树，找到与 key 匹配的叶子节点并赋值。返回是否找到了"""
        if isinstance(node, dict):
            # 直接命中
            if key in node:
                old = node[key]
                # 只改简单类型或同层级字段，不深入已设置的对象
                if not isinstance(old, (dict, list)):
                    node[key] = value
                    logger.info(f"[set_nested] ✓ 命中! '{key}': {old} => {value}")
                    return True
            # 继续递归子节点
            found = False
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    if self._set_nested_value_recursive(v, key, value):
                        found = True
            return found
        elif isinstance(node, list):
            found = False
            for item in node:
                if isinstance(item, (dict, list)):
                    if self._set_nested_value_recursive(item, key, value):
                        found = True
            return found
        return False

    # ==================== 分页循环处理 ====================

    def build_pagination_request(
        self,
        task: dict,
        cookie_header: str,
        page_number: int = 1
    ) -> dict:
        """
        构建带分页参数的请求配置
        翻页时直接在基础请求配置上替换分页字段（page_field/size_field）

        Args:
            task: 任务配置
            cookie_header: Cookie 凭证
            page_number: 当前页码

        Returns:
            httpx 请求配置
        """
        pagination_config = task.get('pagination', {})
        if isinstance(pagination_config, str):
            try:
                pagination_config = json.loads(pagination_config)
            except (json.JSONDecodeError, TypeError):
                pagination_config = {}

        if not pagination_config:
            return self.build_request_config(task, cookie_header)

        base_config = self.build_request_config(task, cookie_header)

        # 分页参数名（从用户配置读取）
        page_field = pagination_config.get('page_field') or 'pageNum'
        size_field = pagination_config.get('size_field') or 'pageSize'
        default_size = pagination_config.get('default_size', 20)

        logger.info(f"[build_pagination] page_number={page_number}, page_field='{page_field}', size_field='{size_field}', default_size={default_size}")

        params = dict(base_config.get('params', {}))  # 拷贝，避免污染原始配置
        body_json = base_config.get('json')

        if body_json and isinstance(body_json, dict):
            # POST 请求：分页参数在 JSON body 中（支持嵌套路径如 data.page.pageIndex）
            # 读取旧值：优先用路径查找，简单字段名则递归搜索
            if '.' in page_field:
                old_val = self._get_value_by_path(body_json, page_field)
            else:
                old_val = self._find_first_value(body_json, page_field)
                if old_val is None:
                    old_val = '(未设置)'
            self._set_value_by_path(body_json, page_field, page_number)
            logger.info(f"[build_pagination] POST body → {page_field}: {old_val} => {page_number}")
            if size_field and size_field != page_field:
                if '.' in size_field:
                    old_sz = self._get_value_by_path(body_json, size_field)
                else:
                    old_sz = self._find_first_value(body_json, size_field)
                    if old_sz is None:
                        old_sz = '(未设置)'
                self._set_value_by_path(body_json, size_field, default_size)
                logger.info(f"[build_pagination] POST body → {size_field}: {old_sz} => {default_size}")
        else:
            # GET 请求：分页参数在 query string 中
            old_val = params.get(page_field, '(未设置)')
            params[page_field] = page_number
            logger.info(f"[build_pagination] GET params → {page_field}: {old_val} => {page_number}")
            if size_field and size_field != page_field:
                old_sz = params.get(size_field, '(未设置)')
                params[size_field] = default_size
                logger.info(f"[build_pagination] GET params → {size_field}: {old_sz} => {default_size}")
            base_config['params'] = params

        return base_config

    def get_total_count(self, response_json: any, pagination_config: dict) -> Optional[int]:
        """
        从响应中获取总记录数（用于判断是否需要翻页）

        Args:
            response_json: API 响应
            pagination_config: 分页配置
                {
                    "total_field": "data.total",   // 总数字段路径
                }
        """
        logger.info(f"[get_total_count] response_json={json.dumps(response_json, ensure_ascii=False) if isinstance(response_json, (dict, list)) else response_json}")
        logger.info(f"[get_total_count] pagination_config={pagination_config}")

        total_field = (pagination_config or {}).get('total_field')
        if not total_field:
            return None

        # 支持嵌套路径（data.page.totalRecord）或简单字段名自动递归搜索
        if '.' in total_field:
            total = self._get_value_by_path(response_json, total_field)
        else:
            total = self._find_first_value(response_json, total_field)
        
        if total is not None:
            try:
                return int(total)
            except (ValueError, TypeError):
                pass
        return None

