
import django_filters
from django.http import FileResponse
from rest_framework.decorators import action

from .serializers import VirtualMachineSerializer, PemFileSerializer
from .models import PemFile
from rest_framework import viewsets, filters, permissions
from rest_framework.response import Response
from .extra_functions import *
import threading
from marketing.models import VmPlan
import time
import servervm.settings as settings
from rest_framework import status
from authentication.permissions import IsOwner


class VmViewSet(viewsets.ModelViewSet):
    serializer_class = VirtualMachineSerializer
    queryset = VirtualMachine.objects.all()
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['active', ]
    filter_backends = [filters.SearchFilter, django_filters.rest_framework.DjangoFilterBackend]
    search_fields = ['code', 'name']
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return VirtualMachine.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        plan = self.request.data["plan"]
        vm_plan = VmPlan.objects.get(id=plan)
        instance = serializer.save(
            user=self.request.user,
            memory=vm_plan.memory,
            vcpus=vm_plan.vcpus,
            storage=vm_plan.storage,
            os=vm_plan.os
        )

        threading.Thread(target=create_vm, args=(instance,)).start()

    def perform_destroy(self, instance):
        instance.maintenance = True
        instance.save()
        threading.Thread(target=delete_vm, args=(instance,)).start()

    def update(self, request, *args, **kwargs):
        current_data = VirtualMachine.objects.get(id=self.request.data["id"])
        plan = self.request.data["plan"]
        vm_plan = VmPlan.objects.get(id=plan)
        current_data.maintenance = True

        if vm_plan.id != current_data.plan:
            current_data.memory = vm_plan.memory
            current_data.vcpus = vm_plan.vcpus
            current_data.storage = vm_plan.storage
            current_data.os = vm_plan.os

        current_data.save()
        memory = current_data.memory
        storage = current_data.storage
        new_storage = self.request.data["storage"]
        print(f"{memory = }, {new_storage = } {storage = }")
        res = super().update(self.request)
        current_data = VirtualMachine.objects.get(id=self.request.data["id"])
        threading.Thread(target=update_vm, args=(current_data, memory, storage)).start()
        return res

    @action(methods=['post'], detail=True, permission_classes=[IsOwner])
    def start(self, request, pk):
        vm = VirtualMachine.objects.get(pk=pk)
        if not vm.maintenance:
            conn = libvirt.open("qemu:///system")
            try:
                dom = conn.lookupByName(vm.code)
                if not dom.isActive():
                    dom.create()
                else:
                    if not vm.active:
                        vm.active = True
                        vm.save()
                    return Response("vm already active")
            except Exception as e:
                print(e)
            vm.active = True
            vm.save()

            return Response("vm started")
        else:
            return Response("vm is at some maintenance please wait ...")

    @action(methods=['post'], detail=True,permission_classes=[IsOwner])
    def stop(self, request, pk):
        vm = VirtualMachine.objects.get(pk=pk)
        if not vm.maintenance:
            conn = libvirt.open("qemu:///system")
            try:
                dom = conn.lookupByName(vm.code)
                try:
                    dom.shutdown()
                except Exception as e:
                    print(e)
                    if vm.active:
                        vm.active = False
                        vm.save()
                    return Response("vm already off")
            except Exception as e:
                print(e)
            vm.active = False
            vm.save()
            return Response("vm shutdown")
        else:
            return Response("vm is at some maintenance please wait ...")

    @action(methods=['post'], detail=True, permission_classes=[IsOwner])
    def restart(self, request, pk):
        vm = VirtualMachine.objects.get(pk=pk)
        if not vm.maintenance:
            conn = libvirt.open("qemu:///system")
            try:
                dom = conn.lookupByName(vm.code)
                if dom.isActive():
                    dom.reboot()
                else:
                    return Response("vm is off")
            except Exception as e:
                print(e)
            return Response("vm is rebooting")
        else:
            return Response("vm is at some maintenance please wait ...")

    @action(methods=['post'], detail=False, permission_classes=[permissions.AllowAny])
    def update_ip(self, request):
        print(request.data)
        mac_address = request.data["mac_address"]
        try:
            vm = VirtualMachine.objects.get(mac_address=mac_address)
            print(f"{vm.name} called for update ip")
            if not vm.ip_address:
                vm.ip_address = request.data["ip_address"]
                print("setting ip address")
                vm.save()
                os.system(f'ssh-keygen -f "/home/ubuntu/.ssh/known_hosts" -R "{vm.ip_address}"')
                if not os.path.exists(f"~/servervm/media/{vm.user.username}"):
                    os.makedirs(f"~/servervm/media/{vm.user.username}")
                os.system(f"ssh-keygen -q -t rsa -N '' -f /home/ubuntu/servervm/media/{vm.user.username}/{vm.code} <<y")
                time.sleep(10)
                os.system(
                    f"sshpass -p '{settings.vm_template_password}' ssh-copy-id -f -i {vm.pem_file.file_path}.pub -o StrictHostKeyChecking=no user@{vm.ip_address} ")
                print("one")
                os.system(
                    f"sshpass -p '{settings.vm_template_password}' ssh -o StrictHostKeyChecking=no user@{vm.ip_address} bash /var/local/setup.sh > err.html ")
        except VirtualMachine.DoesNotExist:
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(status=status.HTTP_202_ACCEPTED)

    @action(methods=['post'], detail=False,permission_classes=[permissions.AllowAny])
    def set_vpn_ip(self, request):
        mac_address = request.POST["mac_address"]
        try:
            vm = VirtualMachine.objects.get(mac_address=mac_address)
            if not vm.vpn_ip:
                vm.vpn_ip = request.POST["vpn_ip"]
                vm.virtual_mac = request.POST["virtual_mac"]
                vm.save()
        except VirtualMachine.DoesNotExist:
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(status=status.HTTP_202_ACCEPTED)

    # @action(methods=["post"],detail=True,permission_classes=[IsOwner])
    # def renew_payment(self, request, pk):
    #     month = request.data["month"]
    #     vm = VirtualMachine.objects.get(pk=pk)
    #     vm_req = Transaction.objects.create(user=request.user,vm=vm,name=vm.name,plan=vm.plan,month=month,pem_file=vm.pem_file)
    #     payment_url = get_payment_link(request.user, vm_req)
    #     if payment_url:
    #         return Response({"payment_url": payment_url},status=status.HTTP_202_ACCEPTED)
    #     return Response({"detail": "payment link creation failed"}, status=status.HTTP_406_NOT_ACCEPTABLE)
    #


class PemFileViewSet(viewsets.ModelViewSet):
    """
    Api end point to generate pem file
    """
    serializer_class = PemFileSerializer
    queryset = PemFile.objects.all()
    http_method_names = ["get", "post", "delete"]
    permission_classes = [IsOwner,permissions.IsAuthenticated]

    def get_queryset(self):
        return PemFile.objects.filter(user=self.request.user.id)

    def perform_create(self, serializer):
        name = self.request.data['name']
        os.makedirs(f"/home/ubuntu/servervm/media/{self.request.user}", exist_ok=True)
        instance = serializer.save(user=self.request.user)
        instance.file_path = f"/home/ubuntu/servervm/media/{self.request.user}/{instance.code}"
        instance.save()
        os.system(f"ssh-keygen -q -t rsa -N '' -f /home/ubuntu/servervm/media/{self.request.user}/{instance.code}<<y")

    @action(methods=["get"], detail=True)
    def download_file(self, request, pk):
        pem_file = PemFile.objects.get(pk=pk)
        if not pem_file.downloaded:
            pem = open(pem_file.file_path, 'rb')
            print(pem)
            response = FileResponse(pem, filename=pem_file.name)
            os.remove(pem_file.file_path)
            pem_file.downloaded = 1
            pem_file.save()
            return response
        return Response({"error": "you have already downloaded this file"})



