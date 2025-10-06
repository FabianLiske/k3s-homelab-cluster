FROM telegraf:alpine

RUN apk add --no-cache ipmitool net-snmp-libs && \
    ln -sf /usr/sbin/ipmitool /usr/bin/ipmitool

COPY telegraf-ipmitool.sh /usr/local/bin/telegraf-ipmitool
RUN chmod +x /usr/local/bin/telegraf-ipmitool

COPY mibs/*.mib /usr/share/snmp/mibs/