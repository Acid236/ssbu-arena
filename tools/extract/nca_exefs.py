import struct, os, sys
from Crypto.Cipher import AES
from Crypto.Util import Counter
keys={}
for l in open(os.path.expanduser('~/.switch/prod.keys')):
    if '=' in l:
        k,v=l.split('=',1); keys[k.strip()]=bytes.fromhex(v.strip())
def xts_dec(key,data,sector0,ss=0x200):
    k1,k2=AES.new(key[:16],AES.MODE_ECB),AES.new(key[16:],AES.MODE_ECB)
    out=bytearray()
    for s in range(len(data)//ss):
        t=int.from_bytes(k2.encrypt((sector0+s).to_bytes(16,'big')),'little')
        for b in range(0,ss,16):
            blk=data[s*ss+b:s*ss+b+16]; tb=t.to_bytes(16,'little')
            out+=bytes(x^y for x,y in zip(k1.decrypt(bytes(x^y for x,y in zip(blk,tb))),tb))
            t<<=1
            if t>>128: t=(t&((1<<128)-1))^0x87
    return bytes(out)
nca=sys.argv[1]; f=open(nca,'rb')
h=xts_dec(keys['header_key'],f.read(0xC00),0)
assert h[0x200:0x204]==b'NCA3',h[0x200:0x204]
gen=max(h[0x206],h[0x220]); gen=max(gen-1,0)
rights=h[0x230:0x240]
print('content type',h[0x205],'keygen index %02x'%gen,'rights',rights.hex(),'titleid %016x'%struct.unpack('<Q',h[0x210:0x218])[0])
tik=open(sys.argv[2],'rb').read()
assert tik[0x2A0:0x2B0]==rights
key=AES.new(keys['titlekek_%02x'%gen],AES.MODE_ECB).decrypt(tik[0x180:0x190])
for i in range(4):
    s,e=struct.unpack('<II',h[0x240+i*16:0x248+i*16])
    if not e: continue
    fh=h[0x400+i*0x200:0x600+i*0x200]
    print('section',i,'off %x size %x'%(s*0x200,(e-s)*0x200),'fstype',fh[2],'hashtype',fh[3],'crypto',fh[4])
    if fh[2]!=1: continue
    pfs_off,pfs_size=struct.unpack('<QQ',fh[0x40:0x50])
    ctr_hi=fh[0x140:0x148][::-1]
    def read(off,size,base=s*0x200+pfs_off):
        a=base+off; al=a&~0xF
        f.seek(al); d=f.read((a-al+size+15)&~0xF)
        c=AES.new(key,AES.MODE_CTR,counter=Counter.new(64,prefix=ctr_hi,initial_value=al>>4))
        return c.decrypt(d)[a-al:a-al+size]
    hd=read(0,16); assert hd[:4]==b'PFS0',hd
    n,st=struct.unpack('<II',hd[4:12])
    tbl=read(16,24*n+st); strs=tbl[24*n:]
    os.makedirs('exefs',exist_ok=True)
    for j in range(n):
        o,sz,so,_=struct.unpack('<QQII',tbl[j*24:j*24+24])
        name=strs[so:strs.index(b'\0',so)].decode()
        print('  %10d %s'%(sz,name))
        open('exefs/'+name,'wb').write(read(16+24*n+st+o,sz))
