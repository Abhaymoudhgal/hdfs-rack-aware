#!/bin/bash

HOST="$1"

case "$HOST" in

  rack1node1|*rack1node1*)
    echo "/rack1"
    ;;
  rack1node2|*rack1node2*)
    echo "/rack1"
    ;;
  rack1node3|*rack1node3*)
    echo "/rack1"
    ;;

  rack2node1|*rack2node1*)
    echo "/rack2"
    ;;
  rack2node2|*rack2node2*)
    echo "/rack2"
    ;;
  rack2node3|*rack2node3*)
    echo "/rack2"
    ;;

  *)
    echo "/default-rack"
    ;;
esac