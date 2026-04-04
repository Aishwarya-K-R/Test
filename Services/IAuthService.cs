using Patient_Management_System.Models;

namespace Patient_Management_System.Services
{
    public interface IAuthService
    {
        Task Signup(User user);
        Task<string> Login(User user);
    }
}
