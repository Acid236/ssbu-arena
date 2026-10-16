#!/bin/sh
# Round 17: the validation of ssbu_p17.exe in one look (read only).
cd "$(dirname "$0")/.." || exit 1
L=tests/logs
cmpn() {  # <new hash> <reference hash>: equal over the common lines?
    [ -s "$1" ] || { echo "  $1: no hash lines"; return; }
    n=$(wc -l < "$1"); m=$(wc -l < "$2"); k=$n; [ "$m" -lt "$k" ] && k=$m
    if [ "$(head -n "$k" "$1" | md5sum)" = "$(head -n "$k" "$2" | md5sum)" ]; then echo "  $1 ($n lines) = $2 ($m lines) over $k lines: IDENTICAL"; else echo "  $1 ($n) vs $2 ($m): DIFFERENT, first at line $(cmp "$1" "$2" | head -1)"; fi
}
echo "state hash:"
cmpn $L/vk13_p17_ica.hash $L/vk13_p16_g2_icag.hash
cmpn $L/vk13_p17_ica0.hash $L/vk13_p16_g2_icag.hash
cmpn $L/vk13_p17_bf.hash $L/vk13_p16_g2_bfg.hash
cmpn $L/vk13_p17_bf0.hash $L/vk13_p16_g2_bfg.hash
cmpn $L/vk13_p17_zt.hash $L/vk13_p16_g2_ztg.hash
cmpn $L/vk13_p17_i2.hash $L/vk13_p16t_ica2p_d.hash
for t in ica ica0 bf bf0 zt i2 list final; do
    f=$L/vk13_p17_$t.log; [ -e "$f" ] || continue
    echo "== $t: $(cat $L/vk13_p17_$t.shared 2>/dev/null | tr '\n' ' ')"
    grep -h "shot: fight frame .* saved\|debug end: .* reached\|HOST EXCEPTION\|TRAP\|nvn_vk_flash: [^d]\|display-timing: fight\|first battle frame\|debug match: requested" "$f" | cut -c1-260 | tail -14
    grep -c "nvn_vk_flash:.*FLASH\|white flash" "$f" | sed 's/^/  flash report lines: /'
    grep -h "nvn_vk_first: [^f]" "$f" | tail -2 | cut -c1-600
done
