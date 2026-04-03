namespace Patient_Management_System.Exceptions
{
    public class DuplicateEmailException(string email) : Exception($"Patient/User with email {email} already exists!!!")
    {
    }
}