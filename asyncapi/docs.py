import dataclasses
import importlib
import json
import os.path
from enum import Enum
from functools import partial
from http import HTTPStatus
from typing import Any, Dict, Iterable, List, Optional

import jinja2
import typer
import uvicorn
import yaml
from apidaora import (
    ContentType,
    Response,
    RoutedControllerTypeHint,
    appdaora,
    css,
    html,
    javascript,
    route,
)

from asyncapi import Operation, Specification
from asyncapi.builder import build_spec_from_path
from asyncapi.schema import type_as_jsonschema
from asyncapi.specification_v2_0_0 import as_camel_case


def main(
    api_module: str = typer.Option('', envvar='ASYNCAPI_MODULE'),
    host: str = typer.Option('0.0.0.0', envvar='ASYNCAPI_HOST'),
    port: int = typer.Option(5000, envvar='ASYNCAPI_PORT'),
    path: Optional[str] = typer.Option(None, envvar='ASYNCAPI_PATH'),
) -> None:
    if path:
        spec = build_spec_from_path(path)
    else:
        spec = getattr(importlib.import_module(api_module), 'spec')

    start(spec, host, port)


def start(spec: Specification, host: str, port: int) -> None:
    controllers = build_yaml_spec_controllers(spec) + [
        build_json_spec_controller(spec)
    ]
    controllers.extend(build_spec_docs_controllers(spec))
    app = appdaora(controllers)
    uvicorn.run(app, host=host, port=port)


def build_yaml_spec_controllers(
    spec: Specification,
) -> List[RoutedControllerTypeHint]:
    def controller() -> Response:
        return Response(
            status=HTTPStatus.OK,
            content_type=ContentType.APPLICATION_YAML,
            body=yaml.dump(spec_asjson(spec)),
            headers=(),
        )

    @route.get('/asyncapi.yaml')
    def controller_yaml() -> Response:
        return controller()

    @route.get('/asyncapi.yml')
    def controller_yml() -> Response:
        return controller()

    return [controller_yaml, controller_yml]


def build_json_spec_controller(
    spec: Specification,
) -> RoutedControllerTypeHint:
    @route.get('/asyncapi.json')
    def controller() -> Response:
        return Response(
            status=HTTPStatus.OK,
            content_type=ContentType.APPLICATION_JSON,
            body=json.dumps(spec_asjson(spec), indent=2).encode(),
            headers=(),
        )

    return controller


def spec_asjson(spec: Specification) -> Dict[str, Any]:
    json_spec: Dict[str, Any] = _spec_asjson(spec)
    spec_messages_dict = (
        spec.components.messages
        if spec.components and spec.components.messages
        else {}
    )
    json_spec_messages = {}

    for message_name, message_type in spec_messages_dict.items():
        if message_type.payload:
            json_spec['components']['messages'][message_name][
                'payload'
            ] = type_as_jsonschema(message_type.payload)

            if message_type.name:
                json_spec_messages[message_type.name] = message_name

    for server in json_spec['servers'].values():
        server.pop('name', None)

    for channel_dict, channel in zip(
        json_spec['channels'].values(), spec.channels.values()
    ):
        channel_dict.pop('name', None)

        if 'subscribe' in channel_dict:
            set_operation_message(
                channel_dict['subscribe'],
                channel.subscribe,
                json_spec_messages,
            )

        if 'publish' in channel_dict:
            set_operation_message(
                channel_dict['publish'], channel.publish, json_spec_messages
            )

    return json_spec


def set_operation_message(
    operation_dict: Dict[str, Any],
    operation: Optional[Operation],
    json_spec_messages: Dict[str, str],
) -> None:
    operation_dict['message'].pop('contentType', None)

    if (
        operation
        and operation.message
        and operation.message.name
        and operation.message.name in json_spec_messages
    ):
        operation_dict['message'] = {
            '$ref': (
                '#/components/messages/'
                f'{json_spec_messages[operation.message.name]}'
            )
        }

    elif operation and operation.message and operation.message.payload:
        operation_dict['message']['payload'] = type_as_jsonschema(
            operation.message.payload
        )


def _spec_asjson(generic_value: Any) -> Any:
    json_value: Any

    if dataclasses.is_dataclass(generic_value):
        json_value = {}

        for field in dataclasses.fields(generic_value):
            field_value = _spec_asjson(
                getattr(generic_value, field.name, None)
            )

            if field_value is not None and field_value != '':
                json_value[as_camel_case(field.name)] = field_value

    elif isinstance(generic_value, dict):
        json_value = {k: _spec_asjson(v) for k, v in generic_value.items()}

    elif not isinstance(generic_value, str) and isinstance(
        generic_value, Iterable
    ):
        json_value = [_spec_asjson(v) for v in generic_value]

    elif isinstance(generic_value, Enum):
        json_value = generic_value.value

    else:
        json_value = generic_value

    return json_value


def build_spec_docs_controllers(
    spec: Specification,
) -> List[RoutedControllerTypeHint]:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = partial(os.path.join, current_dir, 'docs-template', 'template')
    template_loader = jinja2.FileSystemLoader(
        searchpath=os.path.join(current_dir, 'docs-template')
    )
    template_env = jinja2.Environment(loader=template_loader)
    json_spec = spec_asjson(spec)

    @route.get('/docs')
    def index_controller() -> Response:
        template = template_env.get_template('template/index.html')
        return html(template.render(params={}, asyncapi=json_spec))

    @route.get('/css/tailwind.min.css')
    def tailwind_controller() -> Response:
        return css(open(file_path('css', 'tailwind.min.css')).read())

    @route.get('/css/atom-one-dark.min.css')
    def atom_one_dark_controller() -> Response:
        return css(open(file_path('css', 'atom-one-dark.min.css')).read())

    @route.get('/css/main.css')
    def main_css_controller() -> Response:
        return css(open(file_path('css', 'main.css')).read())

    @route.get('/js/highlight.min.js')
    def highlight_controller() -> Response:
        return javascript(open(file_path('js', 'highlight.min.js')).read())

    @route.get('/js/main.js')
    def main_js_controller() -> Response:
        return javascript(open(file_path('js', 'main.js')).read())

    return [
        index_controller,
        tailwind_controller,
        atom_one_dark_controller,
        main_css_controller,
        highlight_controller,
        main_js_controller,
    ]


def run() -> None:
    typer.run(main)


if __name__ == '__main__':
    run()
