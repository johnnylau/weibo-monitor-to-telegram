#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
if ! pgrep -f 'weibo.py'
then
    python3 "${SCRIPT_DIR}"/weibo.py >> "${SCRIPT_DIR}"/weibo.log 2>&1
fi
