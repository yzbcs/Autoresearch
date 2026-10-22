/* Relocate only LibreOffice's /tmp/OSL_PIPE_* UNIX sockets into this project's
 * cache. LibreOffice 7.3 prefers /tmp even when TMPDIR is set (sal/osl/unx/pipe.cxx).
 * No global configuration, mount, or system binary is changed.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
static const char *mapped(const char *path, char *out, size_t n) {
    const char *base = getenv("FIGURECRAFTER_IPC_DIR");
    const char *name = NULL;
    if (path && !strncmp(path,"/tmp/OSL_PIPE_",14)) name=path+5;
    if (path && !strncmp(path,"/var/tmp/OSL_PIPE_",18)) name=path+9;
    if (!base || !name) return path;
    if (strlen(base)+strlen(name)+2>n) { errno=ENAMETOOLONG; return NULL; }
    strcpy(out,base);strcat(out,"/");strcat(out,name);return out;
}
static int endpoint(int fd, const struct sockaddr *addr, socklen_t len, int isbind) {
    static int (*real_bind)(int,const struct sockaddr*,socklen_t);
    static int (*real_connect)(int,const struct sockaddr*,socklen_t);
    if (!real_bind) real_bind=dlsym(RTLD_NEXT,"bind");
    if (!real_connect) real_connect=dlsym(RTLD_NEXT,"connect");
    if (addr && addr->sa_family==AF_UNIX && len>sizeof(sa_family_t)) {
        const struct sockaddr_un *old=(const struct sockaddr_un*)addr;
        struct sockaddr_un copy=*old;
        const char *p=mapped(old->sun_path,copy.sun_path,sizeof(copy.sun_path));
        if (!p) return -1;
        if (p!=old->sun_path) { addr=(const struct sockaddr*)&copy;
            return isbind?real_bind(fd,addr,sizeof(copy)):real_connect(fd,addr,sizeof(copy)); }
    }
    return isbind?real_bind(fd,addr,len):real_connect(fd,addr,len);
}
int bind(int fd,const struct sockaddr *a,socklen_t n){return endpoint(fd,a,n,1);}
int connect(int fd,const struct sockaddr *a,socklen_t n){return endpoint(fd,a,n,0);}
int unlink(const char *p){static int(*f)(const char*);if(!f)f=dlsym(RTLD_NEXT,"unlink");char b[4096];p=mapped(p,b,sizeof(b));return p?f(p):-1;}
int access(const char *p,int m){static int(*f)(const char*,int);if(!f)f=dlsym(RTLD_NEXT,"access");char b[4096];p=mapped(p,b,sizeof(b));return p?f(p,m):-1;}
int stat(const char *p,struct stat *s){static int(*f)(const char*,struct stat*);if(!f)f=dlsym(RTLD_NEXT,"stat");char b[4096];p=mapped(p,b,sizeof(b));return p?f(p,s):-1;}
int __xstat(int v,const char *p,struct stat *s){static int(*f)(int,const char*,struct stat*);if(!f)f=dlsym(RTLD_NEXT,"__xstat");char b[4096];p=mapped(p,b,sizeof(b));return p?f(v,p,s):-1;}
