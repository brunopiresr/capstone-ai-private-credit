{
  "kind": "Dashboard",
  "metadata": {
    "name": "Credit Monitor",
    "createdAt": "2026-11-13T17:26:09.355753Z",
    "updatedAt": "2026-11-13T17:26:09.355753Z",
    "version": 0,
    "project": "capstone-ai-private-credit"
  },
  "spec": {
    "display": {
      "name": "Credit Monitor",
      "description": null
    },
    "panels": {
      "Newpanel": {
        "kind": "Panel",
        "spec": {
          "display": {
            "name": "Cache Hits"
          },
          "plugin": {
            "kind": "TimeSeriesChart",
            "spec": {
              "legend": {
                "position": "bottom"
              },
              "visual": {
                "display": "bar",
                "connectNulls": false
              },
              "yAxis": {}
            }
          },
          "queries": [
            {
              "kind": "TimeSeriesQuery",
              "spec": {
                "plugin": {
                  "kind": "LogfireTimeSeriesQuery",
                  "spec": {
                    "query": "SELECT\n  time_bucket($resolution, start_timestamp::date) AS x,\n  count(1) AS 'Cache Hits'\nFROM records\nWHERE kind IN ('log') AND span_name ILIKE 'HTML cache hit%'\nGROUP BY x"
                  }
                }
              }
            }
          ]
        }
      },
      "Newpanel-1": {
        "kind": "Panel",
        "spec": {
          "display": {
            "name": "Agent Turns"
          },
          "plugin": {
            "kind": "BarChart",
            "spec": {
              "calculation": "sum",
              "format": {
                "unit": "decimal",
                "shortValues": true
              },
              "sort": "desc",
              "orderBy": "query",
              "mode": "value",
              "showValues": true,
              "legend": {
                "position": "bottom"
              },
              "palette": {
                "name": "default",
                "order": [
                  1,
                  2,
                  3,
                  4,
                  5,
                  6,
                  7,
                  0
                ]
              },
              "orientation": "vertical"
            }
          },
          "queries": [
            {
              "kind": "NonTimeSeriesQuery",
              "spec": {
                "plugin": {
                  "kind": "LogfireNonTimeSeriesQuery",
                  "spec": {
                    "query": "SELECT\n  attributes -> 'agent_name' AS agent,\n  count(*)::int as invocations\nFROM records\nWHERE kind IN ('span') AND span_name = 'agent.turn'\nGROUP BY 1"
                  }
                }
              }
            }
          ]
        }
      },
      "Newpanel-2": {
        "kind": "Panel",
        "spec": {
          "display": {
            "name": "User Review - Category Avg Score"
          },
          "plugin": {
            "kind": "RadarChart",
            "spec": {
              "legend": {
                "position": "bottom"
              },
              "showValues": true,
              "scale": "shared",
              "palette": {
                "base": "#037400"
              }
            }
          },
          "queries": [
            {
              "kind": "NonTimeSeriesQuery",
              "spec": {
                "plugin": {
                  "kind": "LogfireNonTimeSeriesQuery",
                  "spec": {
                    "query": "SELECT\n  attributes -> 'category' AS 'Category',\n  avg((attributes -> 'gen_ai.evaluation.score.value')::decimal) as 'AVG Category Score'\nFROM records\nWHERE kind IN ('log')\n  and span_name = 'gen_ai.evaluation.result'\n  and attributes->'gen_ai.evaluation.score.value' is not null\ngroup by 1"
                  }
                }
              }
            }
          ]
        }
      }
    },
    "layouts": [
      {
        "kind": "Grid",
        "spec": {
          "display": {
            "title": "",
            "collapse": {
              "open": true
            }
          },
          "items": [
            {
              "x": 0,
              "y": 0,
              "width": 8,
              "height": 8,
              "content": {
                "$ref": "#/spec/panels/Newpanel"
              }
            },
            {
              "x": 8,
              "y": 0,
              "width": 16,
              "height": 8,
              "content": {
                "$ref": "#/spec/panels/Newpanel-1"
              }
            },
            {
              "x": 0,
              "y": 8,
              "width": 10,
              "height": 7,
              "content": {
                "$ref": "#/spec/panels/Newpanel-2"
              }
            }
          ]
        }
      }
    ],
    "variables": [],
    "annotations": [],
    "duration": "7d",
    "refreshInterval": "60s",
    "datasources": {},
    "links": []
  }
}